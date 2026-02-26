# -*- coding: utf-8 -*-
"""
Avaliação de extrações usando LLM-as-a-Judge com métricas de precisão e recall.

Autor: Luiz Anísio
Fonte: https://github.com/luizanisio/llms/tree/main/experimentos/agentes-esp-acordao
Data: 14/11/2025

Descrição:
-----------
Avalia qualidade das extrações de espelhos comparando com texto original do acórdão.
Utiliza GPT-5 como juiz para calcular precision, recall e F1-score das extrações
feitas por diferentes modelos (base, agentes, raw).
"""

import pandas as pd
import os, sys, json

# carrega variáveis de ambiente na pasta atual, anterior ou src
import sys
sys.path.append('../src')
sys.path.append('../prompts')
# carrega variáveis de ambiente na pasta atual, anterior ou src
import sys
sys.path.append('../src')
from util import UtilEnv, Util, UtilArquivos, UtilTextos, UtilDataHora
from util_openai import UtilJson
sys.path.append('../prompts')
from util_prompt_experimento import send_prompt
from prompt_espelho_agentes import PAPEL_LLM_AS_A_JUDGE, PROMPT_LLM_AS_A_JUDGE

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


#MODELO_JUIZ = 'gpt-5'  # api da openai - requer chave de API válida no .env em PESSOAL_OPENAI_API_KEY
MODELO_JUIZ = 'or:openai/gpt-5'  # api do openrouter  - requer chave de API válida no .env em PESSOAL_OPENROUTER_API_KEY
MODELO_JUIZ_THINK = 'medium:low' # médio think e lowe verbosity para respostas mais objetivas do juiz

sessao = {}

def print_sessao(linhas=True):
    global sessao
    _resumo = {f' - {k}: {v}' for k, v in sessao.items()}
    _resumo = ' | '.join(sorted(_resumo))
    _linha = '=' * 80
    if linhas:
        print(f'\n{_linha}\nRESUMO SESSÃO: \n{_resumo}\n{_linha}')
    else:
        print(f'RESUMO SESSÃO: {_resumo}')

def avaliar_parada_por_erro(erro):
    if isinstance(erro, str):
       _erro = erro.lower()
    elif isinstance(erro, dict) and len(erro) > 0:
         _erro = erro.get('erro','').lower() or erro.get('erros','').lower()
    if not erro:
        return
    if ('modelo' in _erro and 'não encontrado' in _erro) or \
        ('authorize' in _erro):
        msg = '|' * 60 + '\n'
        _erro = json.dumps(erro, ensure_ascii=False, indent=2) if isinstance(erro, dict) else str(erro)
        msg += f'| ERRO CRÍTICO: {_erro}\n'
        msg += '|' * 60 + '\n'
        print(msg)
        exit(1)

def resposta_ok(arquivo):
    if not os.path.isfile(arquivo):
        return False
    r = UtilArquivos.carregar_arquivo(arquivo)
    r = UtilJson.mensagem_to_json(r, padrao={})
    if len(r) >1 and 'precision' in r and 'recall' in r:
        return True
    return False

def gerar_respostas(row, pasta_extracao):
    global sessao
    id_peca = row['id_peca']
    try:
        arquivo_extracao = os.path.join(pasta_extracao, f'{id_peca}.json')
        arquivo_resposta = os.path.join(pasta_extracao, f'{id_peca}.avaliacao.json')
        arquivo_resposta_log = os.path.join(pasta_extracao, f'{id_peca}.avaliacao.log')
        if resposta_ok(arquivo_resposta):
            sessao['ja_avaliado'] = sessao.get('ja_avaliado', 0) + 1
            return
        texto = row.get('texto') or row.get('integra')
        _linha = '=' * 60

        if not texto or len(texto) < 100:
            print(f'Texto da peça {id_peca} muito curto ou inexistente.')
            sessao['sem_texto'] = sessao.get('sem_texto', 0) + 1
            return {'erro': 'sem_texto', 'nota': 0, 'explicacao': 'Texto da peça muito curto ou inexistente.'}

        if not os.path.isfile(arquivo_extracao):
            # ignora, mas contabiliza para análise posterior 
            # print(f'Arquivo de extração não encontrado para peça {id_peca}.')
            sessao['sem_extracao'] = sessao.get('sem_extracao', 0) + 1
            return {'erro': 'sem_arquivo', 'nota': 0, 'explicacao': 'Arquivo de extração não encontrado'}

        extracao = UtilArquivos.carregar_arquivo(arquivo_extracao)
        extracao = UtilJson.mensagem_to_json(extracao, padrao={})
        if len(extracao) == 0:
            print(f'Arquivo de extração vazio para peça {id_peca}.')
            return {'erro': 'sem_extracao', 'nota': 0, 'explicacao': 'Arquivo de extração vazio'}

        extracao = json.dumps(extracao, ensure_ascii=False, indent=2)    
        msg_prompt = PROMPT_LLM_AS_A_JUDGE.replace('<--texto-->', texto).replace('<--extracao-->', extracao)
        avaliacao = send_prompt(prompt=msg_prompt, papel=PAPEL_LLM_AS_A_JUDGE,
                            sg_modelo=MODELO_JUIZ, 
                            think=MODELO_JUIZ_THINK,
                            sem_erro=True, prompt_retorna_json=True,
                            retorno_resumido=True,
                            temperature=0.0)

        if isinstance(avaliacao, dict) and 'erro' in avaliacao:
            print(f'{_linha}\nErro na resposta do LLM para peça {id_peca}: {avaliacao["erro"]}\n{_linha}\n')
            sessao['com_erro'] = sessao.get('com_erro', 0) + 1
            return

        if (not isinstance(avaliacao, dict)) or len(avaliacao) == 0:
            print(f'\n{_linha}\nArquivo de avaliação inválido para peça {id_peca}.\n{avaliacao}\n{_linha}\n')
            sessao['sem_avaliacao'] = sessao.get('sem_avaliacao', 0) + 1
            return {'erro': 'sem_avaliacao', 'nota': 0, 'explicacao': 'Arquivo de avaliação inválido'}

        # grava a resposta na mesma pasta
        _avaliacao_txt_dump = json.dumps(avaliacao, ensure_ascii=False, indent=2)
        with open(arquivo_resposta_log, 'w') as f:
            _log = f'PROMPT LLM AS A JUDGE:\n{msg_prompt}\n{_linha}\n\nRESPOSTA LLM AS A JUDGE:\n{_avaliacao_txt_dump}'
            f.write(_log)
        with open(arquivo_resposta, 'w') as f:
            f.write(_avaliacao_txt_dump)
        sessao['com_sucesso'] = sessao.get('com_sucesso', 0) + 1
        return avaliacao
    except Exception as e:
        print(f'Erro ao processar peça id_peca={id_peca}: {traceback.format_exc()}')


if __name__ == '__main__':
    #id_peca = ['202200038900.29.', '202200205729.40.']
    #id_peca = '202200205729.40.'
    id_peca = None
    
    # Opcionalmente Limitar quantas avaliações deseja fazer 
    # 0 para todas
    QTD_LLM_AS_A_JUDGE = 0
    print(f'Quantidade de LLM as a Judge por peça: {QTD_LLM_AS_A_JUDGE}')
    PASTA_RAIZ = '../data/'

    # ajuste com as saídas dos modelos que serão avaliadas
    PASTAS_EXTRACAO = [
        'espelhos_agentes_gpt5/',
        'espelhos_agentes_gemma3_12b/',
        'espelhos_agentes_gemma3_27b/',
        'espelhos_base_gpt5/',
        'espelhos_base_gemma3_12b/',
        'espelhos_base_gemma3_27b/',
        'espelhos_raw/',  # se quiser usar o espelho dos dados abertos - mas é diferente do padrão do experimento
    ]
    PASTAS_EXTRACAO = [os.path.join(PASTA_RAIZ, p) for p in PASTAS_EXTRACAO]
    
    DATAFRAME_ESPELHOS = os.path.join(PASTA_RAIZ, 'espelhos_acordaos_artigo2026_com_texto.parquet')
    if not os.path.isfile(DATAFRAME_ESPELHOS):
        print('⚠️ Não foi possível carregar o dataframe de espelhos!')
        print(f'Verifique se o arquivo {DATAFRAME_ESPELHOS} existe!')
        print(f'Utilize o notebook 01_data_preparation.ipynb para gerar o dataframe!')
        exit(0)

    assert os.path.isfile(DATAFRAME_ESPELHOS), f'Arquivo do DataFrame não encontrado: {DATAFRAME_ESPELHOS}'
    pastas_testar = [_ for _ in PASTAS_EXTRACAO]
    PASTAS_EXTRACAO = []
    for p in pastas_testar:
        if not os.path.isdir(p):
           print(f'🚩 Pasta de extração não encontrada: {p}')
        else:
            print(f'✅ Pasta de extração encontrada: {p}')
            PASTAS_EXTRACAO.append(p)
    
    df = pd.read_parquet(DATAFRAME_ESPELHOS)
    # filtra mantendo apenas os que possuem íntegra
    q_total = len(df)
    df = df[df['tem_integra'] == True]
    print('-' * 40)
    print(f'Total de registros com íntegra: {len(df)} de {q_total}')
    print('-' * 40)
    print('Exemplos do dataframe de espelhos:')
    print(df.head(2))
    print('-' * 40)
    
    if isinstance(id_peca, str) and id_peca.strip():
        df = df[df['id_peca'] == id_peca]
        print(f' - filtrado para id_peca={id_peca}, total de {len(df)} peças.')
    elif isinstance(id_peca, list) and len(id_peca) > 0:
        df = df[df['id_peca'].isin(id_peca)]
        print(f' - filtrado para lista de id_peca, total de {len(df)} peças.')
    else:
        if QTD_LLM_AS_A_JUDGE > 0 and QTD_LLM_AS_A_JUDGE < len(df):
            print(f' - selecionando aleatoriamente {QTD_LLM_AS_A_JUDGE} peças de um total de {len(df)} para avaliação LLM as a Judge.')
            df = df.sample(n=QTD_LLM_AS_A_JUDGE, random_state=42).reset_index(drop=True)
    
    print('DataFrame carregado com ', len(df), 'peças para processamento e avaliação LLM-AS-A-JUDGE.')
      
    for PASTA_EXTRACAO in PASTAS_EXTRACAO:
        print(f'\n{"#"*80}\nIniciando avaliações LLM as a Judge para extrações em: {PASTA_EXTRACAO}\n{"#"*80}\n')  
        # Executar extrações em paralelo com threads
        NUM_THREADS = 3  # Ajuste conforme desejar
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            futures = {executor.submit(gerar_respostas, row, PASTA_EXTRACAO): row['id_peca'] for _, row in df.iterrows()}
            
            for future in tqdm(as_completed(futures), desc='Julgando extrações', ncols=60, total=len(df)):
                try:
                    future.result()
                except Exception as e:
                    id_peca = futures[future]
                    raise Exception(f'Erro ao processar peça id_peca={id_peca}: {str(e)}\n{traceback.format_exc()}')
        print_sessao()   
        # for idx, row in df.iterrows():
        #     gerar_respostas(row, PASTA_EXTRACAO)
        #     print_sessao()

        # Carrega dados da peça
        lst = UtilArquivos.listar_arquivos(PASTA_EXTRACAO, mascara='*.json')
        lst = [arq for arq in lst if '.avaliacao.' in arq]
        # Informa onde os arquivos foram salvos
        print('='*80)
        print_sessao(linhas = False)   
        print('.'*80)
        print(f'ARQUIVOS GERADOS: {PASTA_EXTRACAO}')
        print(f'IDS ANALISADOS: {len(df)}')
        print(f' - Total de arquivos: {len(lst)}')
        print('='*80)
        sessao = {}
