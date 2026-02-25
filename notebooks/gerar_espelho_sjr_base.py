import sys
# -*- coding: utf-8 -*-
"""
Geração de espelhos usando abordagem base (prompt único).

Autor: Luiz Anísio
Fonte: https://github.com/luizanisio/llms/tree/main/experimentos/agentes-esp-acordao
Data: 14/11/2025

Descrição:
-----------
Gera espelhos de acórdãos usando abordagem tradicional com prompt único e extenso,
sem divisão em agentes especializados. Serve como baseline para comparação com
abordagem multi-agentes.
"""

# carrega variáveis de ambiente na pasta atual, anterior ou src
import sys
sys.path.append('../src')
sys.path.append('../prompts')
from util import UtilEnv
if not UtilEnv.carregar_env('.env', pastas=['./','../', '../src']):
    raise EnvironmentError('Não foi possível carregar o arquivo .env')

from util import Util, UtilArquivos, UtilTextos, UtilDataHora, UtilCriptografia
from util_openai import get_resposta
# cria um método simplificado de chamada do prompt usando util_openai.get_resposta 
# pode ser adaptado de acordo com a api que for utilizada para as extrações
def prompt(**kwargs):
    if not UtilEnv.get_str('PESSOAL_OPENROUTER_API_KEY'):
        raise EnvironmentError('⚠️ Não foi possível carregar a sua API-KEY do OpenRouter em PESSOAL_OPENROUTER_API_KEY no arquivo .env!')
    if 'sg_modelo' in kwargs:
        kwargs['modelo'] = kwargs.pop('sg_modelo','')
    if 'prompt_retorna_json' in kwargs:
        kwargs['as_json'] = kwargs.pop('prompt_retorna_json')
    kwargs['silencioso'] = True
    res = get_resposta(**kwargs)
    res['tratada'] = True
    return res

import pandas as pd
import os, sys

from tqdm import tqdm
import json
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import time
import traceback

from prompt_espelho_base import PROMPT_BASE_SJR_S3_JSON, PROMPT_USER

UtilEnv.carregar_env('.env', pastas=['../'])

LOCK_SESSAO = Lock()
CRIPT = UtilCriptografia()
PASTA_SAIDAS_EXTRACAO=None
PASTA_RAIZ=None
DATAFRAME_ESPELHOS =None
ARQ_LOGS =None
MODELO_ESPELHO = None
MODELO_ESPELHO_THINK = 'medium'
ARQUIVO_RESUMO_EXTRACAO = None

# configura as variáveis globais - nessa posição permite que as mudanças sejam feitas apenas no __main__ para 
# facilitar gerar os datasets com diferentes modelos
def configurar_extracao(pasta_raiz,pasta_extracao, modelo):
  global PASTA_SAIDAS_EXTRACAO, DATAFRAME_ESPELHOS, ARQ_LOGS, PASTA_RAIZ, MODELO_ESPELHO, ARQUIVO_RESUMO_EXTRACAO
  PASTA_RAIZ=pasta_raiz
  PASTA_SAIDAS_EXTRACAO=os.path.join(pasta_raiz, pasta_extracao)
  DATAFRAME_ESPELHOS = os.path.join(pasta_raiz,'espelhos_acordaos_artigo2026_com_texto.parquet')
  if not os.path.isfile(DATAFRAME_ESPELHOS):
     print('⚠️ Não foi possível carregar o dataframe de espelhos!')
     print(f'Verifique se o arquivo {DATAFRAME_ESPELHOS} existe!')
     print(f'Utilize o notebook 01_data_preparation.ipynb para gerar o dataframe!')
     exit(0)
  MODELO_ESPELHO = modelo
  ARQ_LOGS = os.path.join(PASTA_SAIDAS_EXTRACAO,'log_extracao_base.txt')
  ARQUIVO_RESUMO_EXTRACAO = os.path.join(PASTA_SAIDAS_EXTRACAO,f'resumo_extracao.csv')
  os.makedirs(PASTA_SAIDAS_EXTRACAO, exist_ok=True)

SESSAO = {}
LOG = []
ERROS_CONSECUTIVOS = 0



print( '====================================================================')
print(f'CONEXÕES PREPARADAS, analisando pasta {PASTA_SAIDAS_EXTRACAO} ....')
print( '====================================================================')

def log(txt:str):
    global LOG
    msg_log = UtilDataHora.data_hora_str() + '\t' + str(txt)
    LOG.append(msg_log)
    with open(ARQ_LOGS, 'a') as f:
        f.write(f'{msg_log}\n')
    

def soma_sessao(tipo:str):
    global SESSAO
    with LOCK_SESSAO:
         if tipo not in SESSAO:
            SESSAO[tipo] = 1
         else:
            SESSAO[tipo] += 1
    return SESSAO[tipo]

def print_resumo_sessao():
    print('----------------------------------------------------------------------')
    print('RESUMO:', ' || '.join([f'{c}={v}' for c,v in SESSAO.items()]), f' || LOGS: {len(LOG)}')
    print('----------------------------------------------------------------------')

def get_extracao(row, somente_verificar = False):
    global SESSAO, ERROS_CONSECUTIVOS
    texto = row.get('texto') or row.get('integra')
    if not texto:
        log(f'Registro sem texto para id={row["id_peca"]}')
        return False
    arquivo_saida = os.path.join(PASTA_SAIDAS_EXTRACAO, f'{row["id_peca"]}.json')
    arquivo_resumo = os.path.join(PASTA_SAIDAS_EXTRACAO, f'{row["id_peca"]}_resumo.json')
    if UtilArquivos.tamanho_arquivo(arquivo_saida) > 0:
        if not somente_verificar:
           soma_sessao('existem')
        return True
    if somente_verificar:
        return False
    prompt_user = PROMPT_USER.replace('<<--texto-->>', texto)
    ini = time()
    messages = [
        {"role": "system", "content": PROMPT_BASE_SJR_S3_JSON},
        {"role": "user", "content": prompt_user}]
    try:
        espelho_res = prompt(prompt = messages, 
                            sg_modelo=MODELO_ESPELHO, papel='', 
                            think = MODELO_ESPELHO_THINK,
                            sem_erro=True, 
                            prompt_retorna_json=True,
                            temperature=0, 
                            retorno_resumido=True)
        ERROS_CONSECUTIVOS = 0
    except Exception as e:
        ERROS_CONSECUTIVOS += 1
        print(f'ERRO: {e}\n{traceback.format_exc()}')
        Util.pausa(5)
        soma_sessao('erro-api')
        log(f'Erro gerando espelho id={row["id_peca"]} >> {traceback.format_exc()}')
        return False
    if 'erro' in espelho_res:
        soma_sessao('erro-espelho')
        log(f'Erro gerando espelho id={row["id_peca"]} >> {espelho_res}')
        return False
    try:
        tratada = espelho_res.pop('tratada',False)
        if 'erro' in espelho_res:
           espelho = {'erro': espelho_res['erro']}
        elif not tratada:
           resposta = espelho_res.get('response','')
           espelho = UtilTextos.mensagem_to_json(resposta, padrao=resposta)
        else:
           espelho = espelho_res.get('resposta')
        
    except Exception as e:
        soma_sessao('erro-json')
        log(f'Erro convertendo espelho em json id={row["id_peca"]} >> {traceback.format_exc()}')
        return False
    usage = espelho_res.get('usage',{})
    resumo = {  "input_tokens": usage.get('prompt_tokens'),
                "output_tokens": usage.get('completion_tokens'),
                "reasoning_tokens": usage.get('completion_tokens_details',{}).get('reasoning_tokens'),
                "cached_tokens": usage.get('prompt_tokens_details',{}).get('cached_tokens'),
                "finish_reason": espelho_res.get('finish_reason'),
                "model": MODELO_ESPELHO,
                "think": MODELO_ESPELHO_THINK,
                "time": time()-ini,
                "id_peca": row['id_peca'],
                "model_id": espelho_res.get('model')
                }
        
    with open(arquivo_saida, 'w') as f:
         if isinstance(espelho, str):
            f.write(espelho)
         else:
            f.write(json.dumps(espelho, indent=2, ensure_ascii=False))                            
    with open(arquivo_resumo, 'w') as f:
         f.write(json.dumps(resumo, indent=2, ensure_ascii=False))
    soma_sessao('RESUMO CRIADO')
    log(f'Extração realizada id={row["id_peca"]} >> {time()-ini:.1f}s ')
    return True
    
CAMPOS_RESUMO_DF = {'id_peca','id_espelho','sg_ramo_direito','sg_classe','num_ministro','ano','nomeOrgaoJulgador',
                    'input_tokens','output_tokens', 'reasoning_tokens','cached_tokens',
                    'finish_reason','model','think','time','erro'}
def get_resumo_espelho(row):
    ''' O resumo é obrigatoriamente gerado junto com a extração e no formato JSON.
        Dados pode não ser json se houver erro na geração do espelho.
    '''
    arquivo_dados = os.path.join(PASTA_SAIDAS_EXTRACAO, f'{row["id_peca"]}.json')
    arquivo_resumo = os.path.join(PASTA_SAIDAS_EXTRACAO, f'{row["id_peca"]}_resumo.json')
    if not os.path.isfile(arquivo_resumo):
        return {}
    try:
        resumo = UtilArquivos.carregar_json(arquivo_resumo)
    except Exception as e:
        raise Exception(f'Erro lendo resumo {arquivo_resumo}: {e}')
    try:
        dados = UtilArquivos.carregar_json(arquivo_dados)
    except Exception as e:
        dados = {'erro': f'Erro {e}'}
    # campos para o resumo
    res = {c:v for c,v in dados.items() if c in CAMPOS_RESUMO_DF}
    resumo = {c:v for c,v in resumo.items() if c in CAMPOS_RESUMO_DF}
    linha = {c:v for c,v in dict(row).items() if c in CAMPOS_RESUMO_DF}
    res.update(resumo)
    res.update(linha)
    res['time'] = int(resumo.get('time',0))
    # Retorna também uma estatística simples do conteúdo extraído
    res['qtd_teses'] = len(dados.get('teseJuridica',[])) if isinstance(dados.get('teseJuridica',[]), list) else 0
    res['qtd_jurisprudencias'] = len(dados.get('jurisprudenciaCitada',[])) if isinstance(dados.get('jurisprudenciaCitada',[]), list) else 0
    res['qtd_referencias'] = len(dados.get('referenciasLegislativas',[])) if isinstance(dados.get('referenciasLegislativas',[]), list) else 0
    res['qtd_notas'] = len(dados.get('notas',[])) if isinstance(dados.get('notas',[]), list) else 0
    res['qtd_info_complementares'] = len(dados.get('informacoesComplementares',[])) if isinstance(dados.get('informacoesComplementares',[]), list) else 0
    res['qtd_termos_auxiliares'] = len(dados.get('termosAuxiliares',[])) if isinstance(dados.get('termosAuxiliares',[]), list) else 0
    res['qtd_temas'] = len(dados.get('tema',[])) if isinstance(dados.get('tema',[]), list) else 0
    return res

if __name__ == '__main__':

    # o nome do modelo "o:" indica para a classe usar o openrouter.ai     
    # realizar uma rodada completa para cada modelo que desejar
    configurar_extracao(pasta_raiz ='../data',
                        pasta_extracao='espelho_base_gemma3_12b',
                        modelo =  'or:google/gemma-3-12b-it')

    assert os.path.isdir(PASTA_SAIDAS_EXTRACAO), 'Pasta de saída não existe!'

    print(f'Carregando dataframe: {DATAFRAME_ESPELHOS}')
    df = pd.read_parquet(DATAFRAME_ESPELHOS)
    assert os.path.isfile(DATAFRAME_ESPELHOS), 'Dataframe de espelhos não existe!'
    
    # filtra mantendo apenas os que possuem íntegra
    q_total = len(df)
    df = df[df['tem_integra'] == True]
    print('-' * 40)
    print(f'Total de registros com íntegra: {len(df)} de {q_total}')
    print('-' * 40)
    print('Exemplos do dataframe de espelhos:')
    print(df.head(2))
    print('-' * 40)

    tempo_resumo = time()

    # id_peca é uma chave arbitrária para rastreabilidade e observabilidade dos registros no experimento
    existem = []
    for i, row in tqdm(df.iterrows(), desc = 'Verificando peças com extração', ncols = 60, total=len(df)):
        if get_extracao(row, somente_verificar=True):    
           existem.append(row['id_peca'])
    total = len(df)
    df_extrair = df[~df['id_peca'].isin(existem)]
    if len(existem)  > 0:
        print('-' * 40)
        print(f'ℹ️ Ignorando {len(existem)}/{total} registros com extração encontrada')
        print('-' * 40)

    # caso queira uma rodada de teste
    # df_extrair = df_extrair[:5] 

    # Executar extrações em paralelo com threads
    NUM_THREADS = 3  # Ajuste conforme desejar
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = {executor.submit(get_extracao, row): row['id_peca'] for _, row in df_extrair.iterrows()}
        
        for future in tqdm(as_completed(futures), desc='Extraindo espelhos', ncols=60, total=len(df_extrair)):
            try:
                future.result()
            except Exception as e:
                id_peca = futures[future]
                log(f'Erro na thread para id={id_peca}: {traceback.format_exc()}')

    # consolida um dataframe de resumo
    df_consolidado = []
    for i, row in tqdm(df.iterrows(), desc = 'Consolidando resumos', ncols = 60, total=len(df)):
        resumo = get_resumo_espelho(row)
        if any(resumo):
            df_consolidado.append(resumo)
            print('|' * 60)
            print(resumo)
    print('-' * 40)
    print(f'Gravando resumo da extração em {ARQUIVO_RESUMO_EXTRACAO}')
    df_consolidado = pd.DataFrame(df_consolidado)
    df_consolidado['time'] = df_consolidado['time'].astype(int)
    df_consolidado.to_csv(ARQUIVO_RESUMO_EXTRACAO, index=False, encoding='utf-8-sig')
    
    print_resumo_sessao()
    
    print('\n####################\nFIM')
    if any(LOG):
       print(f'LOGS: {len(LOG)} Erros e/ou Avisos gravados em "{ARQ_LOGS}"')
