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
from util import UtilEnv, Util, UtilArquivos, UtilTextos, UtilDataHora
sys.path.append('../prompts')
from prompt_espelho_base import PROMPT_BASE_SJR_S3_JSON, PROMPT_USER
from util_prompt_experimento import send_prompt

import pandas as pd
import os, sys

from tqdm import tqdm
import json
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import time
import traceback


UtilEnv.carregar_env('.env', pastas=['../'])

LOCK_SESSAO = Lock()
SESSAO = {}
LOG = []
ERROS_CONSECUTIVOS = 0

def criar_cfg(pasta_raiz, pasta_extracao, modelo, modelo_think='medium'):
    """Cria o dicionário de configuração para uma rodada de extração.

    Centraliza todos os caminhos e parâmetros, eliminando variáveis globais
    de configuração e tornando as dependências explícitas entre funções.
    """
    pasta_saidas = os.path.join(pasta_raiz, pasta_extracao)
    arq_dataframe = os.path.join(pasta_raiz, 'espelhos_acordaos_artigo2026_com_texto.parquet')
    if not os.path.isfile(arq_dataframe):
        print('⚠️ Não foi possível carregar o dataframe de espelhos!')
        print(f'Verifique se o arquivo {arq_dataframe} existe!')
        print(f'Utilize o notebook 01_data_preparation.ipynb para gerar o dataframe!')
        exit(0)
    os.makedirs(pasta_saidas, exist_ok=True)
    return {
        'pasta_raiz': pasta_raiz,
        'pasta_saidas': pasta_saidas,
        'arq_dataframe': arq_dataframe,
        'arq_logs': os.path.join(pasta_saidas, 'log_extracao_base.txt'),
        'arq_resumo': os.path.join(pasta_saidas, 'resumo_extracao.csv'),
        'modelo': modelo,
        'modelo_think': modelo_think,  # nem todo modelo suporta; verificar documentação
    }

def log(txt, cfg):
    global LOG
    msg_log = UtilDataHora.data_hora_str() + '\t' + str(txt)
    LOG.append(msg_log)
    with open(cfg['arq_logs'], 'a') as f:
        f.write(f'{msg_log}\n')
    

def soma_sessao(tipo:str):
    ''' Soma contadores simples para monitorar a sessão de extração.
        Tipos comuns: 'existem', 'erro-api', 'erro-espelho', 'erro-json', 'RESUMO CRIADO', etc. 
        Permitindo a impressão de um resumo ao final da sessão com as principais estatísticas. '''
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

def get_extracao(row, cfg, somente_verificar=False):
    """Extrai espelho de um acórdão usando prompt base.

    Args:
        row: Linha do dataframe com dados do acórdão.
        cfg: Dicionário de configuração da rodada (caminhos, modelo, etc.).
        somente_verificar: Se True, apenas verifica se a extração já existe.
    """
    global ERROS_CONSECUTIVOS
    texto = row.get('texto') or row.get('integra')
    if not texto:
        log(f'Registro sem texto para id={row["id_peca"]}', cfg)
        return False
    arquivo_saida = os.path.join(cfg['pasta_saidas'], f'{row["id_peca"]}.json')
    arquivo_resumo = os.path.join(cfg['pasta_saidas'], f'{row["id_peca"]}_resumo.json')
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
        espelho_res = send_prompt( prompt = messages, 
                                   sg_modelo=cfg['modelo'], papel='', 
                                   think = cfg['modelo_think'],
                                   prompt_retorna_json=True,
                                   temperature=0)
        ERROS_CONSECUTIVOS = 0
    except Exception as e:
        ERROS_CONSECUTIVOS += 1
        print(f'ERRO: {e}\n{traceback.format_exc()}')
        Util.pausa(5)
        soma_sessao('erro-api')
        log(f'Erro gerando espelho id={row["id_peca"]} >> {traceback.format_exc()}', cfg)
        return False
    if 'erro' in espelho_res:
        soma_sessao('erro-espelho')
        log(f'Erro gerando espelho id={row["id_peca"]} >> {espelho_res}', cfg)
        return False
    try:
        tratada = espelho_res.pop('tratada',False)
        if 'erro' in espelho_res:
           espelho = {'erro': espelho_res['erro']}
        elif not tratada:
           resposta = espelho_res.get('resposta','')
           espelho = UtilTextos.mensagem_to_json(resposta, padrao=resposta)
        else:
           espelho = espelho_res.get('resposta')
        
    except Exception as e:
        soma_sessao('erro-json')
        log(f'Erro convertendo espelho em json id={row["id_peca"]} >> {traceback.format_exc()}', cfg)
        return False
    usage = espelho_res.get('usage',{})
    resumo = {  "input_tokens": usage.get('prompt_tokens'),
                "output_tokens": usage.get('completion_tokens'),
                "reasoning_tokens": usage.get('reasoning_tokens'),
                "cached_tokens": usage.get('cached_tokens'),
                "finish_reason": usage.get('finished_reason'),
                "model": cfg['modelo'],
                "think": cfg['modelo_think'],
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
    log(f'Extração realizada id={row["id_peca"]} >> {time()-ini:.1f}s ', cfg)
    return True
    
CAMPOS_RESUMO_DF = {'id_peca','id_espelho','sg_ramo_direito','sg_classe','num_ministro','ano','nomeOrgaoJulgador',
                    'input_tokens','output_tokens', 'reasoning_tokens','cached_tokens',
                    'finish_reason','model','think','time','erro'}
def get_resumo_espelho(row, cfg):
    """Lê e consolida o resumo de uma extração já realizada.

    Args:
        row: Linha do dataframe com dados do acórdão.
        cfg: Dicionário de configuração da rodada.
    """
    arquivo_dados = os.path.join(cfg['pasta_saidas'], f'{row["id_peca"]}.json')
    arquivo_resumo = os.path.join(cfg['pasta_saidas'], f'{row["id_peca"]}_resumo.json')
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

def extrair_dados(pasta_raiz, pasta_extracao, modelo, ids_fixos=None):
    """Executa uma rodada completa de extração de espelhos para um modelo.

    Cria a configuração, carrega o dataframe, filtra registros, executa
    extrações em paralelo e consolida o resumo. Pode ser chamada em loop
    para múltiplos modelos sem depender de variáveis globais de configuração.

    Args:
        pasta_raiz: Pasta raiz dos dados (ex: '../data')
        pasta_extracao: Subpasta para salvar as extrações (ex: 'espelhos_base_gpt5')
        modelo: Identificador do modelo LLM (ex: 'or:openai/gpt-5')
        ids_fixos: Lista opcional de id_peca para filtrar o dataframe (útil para testes)
    """
    # cria configuração da rodada — substitui variáveis globais
    cfg = criar_cfg(pasta_raiz, pasta_extracao, modelo)

    assert os.path.isdir(cfg['pasta_saidas']), f'Pasta de saída não existe: {cfg["pasta_saidas"]}'

    print(f'Carregando dataframe: {cfg["arq_dataframe"]}')
    df = pd.read_parquet(cfg['arq_dataframe'])

    # filtra mantendo apenas os que possuem íntegra
    q_total = len(df)
    df = df[df['tem_integra'] == True]
    print('-' * 40)
    print(f'Total de registros com íntegra: {len(df)} de {q_total}')
    print('-' * 40)

    # filtra por ids fixos de teste, se fornecidos
    if ids_fixos:
        df = df[df['id_peca'].isin(ids_fixos)]
        print(f'ℹ️ Filtrando por {len(ids_fixos)} ids fixos de teste: {len(df)} registros encontrados')
        print('-' * 40)

    print('Exemplos do dataframe de espelhos:')
    print(df.head(2))
    print('-' * 40)

    # verifica peças já extraídas para evitar reprocessamento
    existem = []
    for i, row in tqdm(df.iterrows(), desc='Verificando peças com extração', ncols=60, total=len(df)):
        if get_extracao(row, cfg, somente_verificar=True):
           existem.append(row['id_peca'])
    total = len(df)
    df_extrair = df[~df['id_peca'].isin(existem)]
    if len(existem) > 0:
        print('-' * 40)
        print(f'ℹ️ Ignorando {len(existem)}/{total} registros com extração encontrada')
        print('-' * 40)

    # executa extrações em paralelo com threads
    NUM_THREADS = 3
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = {executor.submit(get_extracao, row, cfg): row['id_peca'] for _, row in df_extrair.iterrows()}

        for future in tqdm(as_completed(futures), desc='Extraindo espelhos', ncols=60, total=len(df_extrair)):
            try:
                future.result()
            except Exception as e:
                id_peca = futures[future]
                log(f'Erro na thread para id={id_peca}: {traceback.format_exc()}', cfg)

    # consolida um dataframe de resumo com estatísticas da extração
    df_consolidado = []
    for i, row in tqdm(df.iterrows(), desc='Consolidando resumos', ncols=60, total=len(df)):
        resumo = get_resumo_espelho(row, cfg)
        if any(resumo):
            df_consolidado.append(resumo)
            print('|' * 60)
            print(resumo)
    print('-' * 40)
    print(f'Gravando resumo da extração em {cfg["arq_resumo"]}')
    df_consolidado = pd.DataFrame(df_consolidado)
    if len(df_consolidado) > 0:
        print(f'Número de resumos consolidados: {len(df_consolidado)}')
        df_consolidado['time'] = df_consolidado['time'].astype(int)
    df_consolidado.to_csv(cfg['arq_resumo'], index=False, encoding='utf-8-sig')

    print_resumo_sessao()

    if any(LOG):
       print(f'LOGS: {len(LOG)} Erros e/ou Avisos gravados em "{cfg["arq_logs"]}"')

##################################################################
### Ajustes para rodar o experimento - ponto de entrada principal
##################################################################
if __name__ == '__main__':

    # [TAG: EXTRACTION_TEST_IDS]
    # lista opcional de ids para rodadas de teste (None = todos os registros)
    ids_fixos_teste = ['202202853462.20230510.', '202201555326.20220614.']
    #ids_fixos_teste = None  # descomente para processar todos os registros

    ''' Pasta                       ModelApi Openrouter       Api OpenAi
        --------------------------------------------------------------------
        espelhos_base_gpt5         or:openai/gpt-5           openai/gpt-5
        espelhos_base_gemma3_12b   or:google/gemma-3-12b-it
        espelhos_base_gemma3_27b   or:google/gemma-3-27b-it
    '''
    #####################################################################################################
    # [TAG: EXTRACTION_BASE_MODELS]
    # Como usar: escolha a pasta de saída e o modelo desejado,
    # lembrando que o modelo deve ser compatível com a API escolhida (openrouter ou openai).
    # o nome do modelo "or:" indica para a classe usar o openrouter.ai
    # realizar uma rodada completa para cada modelo que desejar
    lista_modelo_pasta = [
        ('espelhos_base_gpt5', 'or:openai/gpt-5'),
        ('espelhos_base_gemma3_12b', 'or:google/gemma-3-12b-it'),
        ('espelhos_base_gemma3_27b', 'or:google/gemma-3-27b-it')
    ]
    # loop de rodadas: executa extração completa para cada modelo configurado
    for pasta, modelo in lista_modelo_pasta:
        print(f'\n{"#"*20} INICIANDO RODADA PARA MODELO {modelo} {"#"*20}\n')
        print(f'- Pasta de saída: {pasta}')
        extrair_dados(pasta_raiz='../data',
                      pasta_extracao=pasta,
                      modelo=modelo,
                      ids_fixos=ids_fixos_teste)

    print('\n####################\nFIM')
