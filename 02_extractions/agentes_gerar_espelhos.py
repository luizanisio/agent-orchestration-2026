
# -*- coding: utf-8 -*-
"""
Script para geração paralela de espelhos de acórdãos usando agentes especializados.

Autor: Luiz Anísio
Fonte: https://github.com/luizanisio/llms/tree/main/experimentos/agentes-esp-acordao
Data: 14/11/2025

Descrição:
-----------
Processa em paralelo um conjunto de acórdãos jurídicos (peças processuais) e gera
espelhos estruturados através do sistema de agentes orquestrados. Suporta diferentes
modelos LLM (GPT-5, Gemma-3) e mantém sessão de controle com estatísticas de execução.
"""

# carrega variáveis de ambiente na pasta atual, anterior ou src
import sys
sys.path.append('../src')
from util import UtilEnv, Util, UtilArquivos, UtilTextos, UtilDataHora
sys.path.append('../prompts')
from util_prompt_experimento import send_prompt

# outras dependências    
import pandas as pd
import os, json
from agentes_orquestrador import AgenteOrquestradorEspelho
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from threading import Lock

# estado mutável de sessão — compartilhado entre threads durante a extração
LOCK_LOG = Lock()
sessao = {}

def criar_cfg(pasta_raiz, pasta_extracao, modelo, modelo_think='medium', callable_modelo=None):
    """Cria o dicionário de configuração para uma rodada de extração por agentes.

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
    arq_logs = os.path.join(pasta_saidas, 'log_inconsistencias.txt')
    return {
        'pasta_raiz': pasta_raiz,
        'pasta_saidas': pasta_saidas,
        'arq_dataframe': arq_dataframe,
        'arq_logs': arq_logs,
        'modelo': modelo,
        'modelo_think': modelo_think,       # nem todo modelo suporta; verificar documentação
        'callable_modelo': callable_modelo,  # função de chamada do modelo (ex: send_prompt)
    }

def print_sessao():
    global sessao
    _resumo = {f' - {k}: {v}' for k, v in sessao.items()}
    _resumo = ' | '.join(sorted(_resumo))
    _linha = '=' * 80
    print(f'\n{_linha}\nRESUMO SESSÃO: \n{_resumo}\n{_linha}')

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

def registrar_log_inconsistencia(id_peca, tipo_inconsistencia, cfg, detalhes=''):
    """Registra inconsistências no arquivo de log de forma thread-safe.

    Args:
        id_peca: Identificador da peça (None para iniciar o arquivo).
        tipo_inconsistencia: Tipo do problema encontrado.
        cfg: Dicionário de configuração da rodada.
        detalhes: Informações adicionais sobre a inconsistência.
    """
    arq_logs = cfg['arq_logs']
    # inicia o arquivo caso id_peca seja None
    if id_peca is None:
        with LOCK_LOG:
            if not os.path.exists(arq_logs):
                with open(arq_logs, 'w', encoding='utf-8') as f:
                    f.write(f'Log de Inconsistências - Iniciado em {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n')
        return
    timestamp = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
    mensagem = f"[{timestamp}] {id_peca} | {tipo_inconsistencia}"
    if detalhes:
        mensagem += f" | {detalhes}"
    mensagem += "\n"

    with LOCK_LOG:
        with open(arq_logs, 'a', encoding='utf-8') as f:
            f.write(mensagem)

def gerar_respostas(row, cfg):
    """Gera espelho de um acórdão usando o sistema de agentes orquestrados.

    Args:
        row: Linha do dataframe com dados do acórdão.
        cfg: Dicionário de configuração da rodada (caminhos, modelo, etc.).
    """
    global sessao
    id_peca = row['id_peca']
    try:
        texto = row.get('texto') or row.get('integra')
        if not texto or len(texto) < 100:
            print(f'Texto da peça {id_peca} muito curto ou inexistente.')
            sessao['sem_texto'] = sessao.get('sem_texto', 0) + 1
            registrar_log_inconsistencia(id_peca, 'SEM_TEXTO', cfg, f'Tamanho: {len(texto) if texto else 0} caracteres')
            return
        
        # Instancia o orquestrador com o texto, id_peca e pasta de observabilidade
        orq = AgenteOrquestradorEspelho(
            id_peca=id_peca, 
            texto_peca=texto,
            pasta_extracao=cfg['pasta_saidas'],
            observabilidade=True,
            modelo_espelho=cfg['modelo'],
            modelo_think=cfg['modelo_think'],
            callable_modelo=cfg['callable_modelo']
        )
        
        # Executa a orquestração
        espelho = orq.executar()
        erros = orq.get_mensagens_erro(espelho)
        #print('ESPELHO: ', json.dumps(espelho, ensure_ascii=False, indent=2))
        #print('ERROS: ', json.dumps(erros, ensure_ascii=False, indent=2))
        if espelho:
            # Verifica se AgenteCampos não retornou nenhum campo (campos_identificados vazio)
            metadados = espelho.get('metadados', {})
            campos_identificados = metadados.get('campos_identificados', [])
            if not campos_identificados or len(campos_identificados) == 0:
                sessao['sem_campos'] = sessao.get('sem_campos', 0) + 1
                registrar_log_inconsistencia(id_peca, 'NENHUM_CAMPO_IDENTIFICADO', cfg, 'AgenteCampos não identificou campos para extração')
            elif erros:
                sessao['com_erro'] = sessao.get('com_erro', 0) + 1
                registrar_log_inconsistencia(id_peca, 'COM_ERRO', cfg, json.dumps(erros, ensure_ascii=False))
                avaliar_parada_por_erro(erros)
            else:
                campos_com_valor = {k: v for k, v in espelho.items() if v not in [None, '', [], {}]}
                campos_sem_valor = {k: v for k, v in espelho.items() if v in [None, '', [], {}]}
                sessao['cp_preenchidos'] = sessao.get('cp_preenchidos', 0) + len(campos_com_valor)
                sessao['cp_vazios'] = sessao.get('cp_vazios', 0) + len(campos_sem_valor)
                
                # Registra se todos os campos estão vazios
                if len(campos_com_valor) == 0:
                    registrar_log_inconsistencia(id_peca, 'TODOS_CAMPOS_VAZIOS', cfg, f'Total de campos: {len(campos_sem_valor)}')
            
            if espelho.get('carregado'):
               sessao['existentes'] = sessao.get('existentes', 0) + 1
            else:
               sessao['concluidos'] = sessao.get('concluidos', 0) + 1
        else:
            sessao['sem_espelho'] = sessao.get('sem_espelho', 0) + 1
            registrar_log_inconsistencia(id_peca, 'SEM_ESPELHO', cfg, 'Orquestrador não retornou espelho')
        
        if (sessao.get('excecoes',0)+sessao.get('concluidos',0)+sessao.get('existentes',0)+sessao.get('com_erro',0))  % 10 == 0:
            print_sessao()
    except Exception as e:
        sessao['excecoes'] = sessao.get('excecoes', 0) + 1
        erro_msg = str(e)
        registrar_log_inconsistencia(id_peca, 'EXCECAO', cfg, erro_msg[:200])
        print(f'Erro ao processar peça id_peca={id_peca}: {traceback.format_exc()}')


def extrair_dados(pasta_raiz, pasta_extracao, modelo, ids_fixos=None):
    """Executa uma rodada completa de extração de espelhos por agentes.

    Cria a configuração, carrega o dataframe, filtra registros, executa
    extrações em paralelo e exibe resumo. Pode ser chamada em loop para
    múltiplos modelos sem depender de variáveis globais de configuração.

    Args:
        pasta_raiz: Pasta raiz dos dados (ex: '../data')
        pasta_extracao: Subpasta para salvar as extrações (ex: 'espelhos_agentes_gemma3_12b')
        modelo: Identificador do modelo LLM (ex: 'or:google/gemma-3-12b-it')
        ids_fixos: Lista opcional de id_peca para filtrar o dataframe (útil para testes)
    """
    # cria configuração da rodada — substitui variáveis globais
    cfg = criar_cfg(pasta_raiz, pasta_extracao, modelo, callable_modelo=send_prompt)

    # inicia o arquivo de log de inconsistências
    registrar_log_inconsistencia(None, None, cfg)

    print(f'Carregando dataframe: {cfg["arq_dataframe"]}')
    df = pd.read_parquet(cfg['arq_dataframe'])
    print(f'DataFrame carregado com {len(df)} peças para processamento.')

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

    # executa extrações em paralelo com threads
    NUM_THREADS = 2
    print(f'Iniciando processamento com {NUM_THREADS} threads...\n- pasta: {cfg["pasta_saidas"]}\n- modelo: {cfg["modelo"]}')

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = {executor.submit(gerar_respostas, row, cfg): row['id_peca'] for _, row in df.iterrows()}

        for future in tqdm(as_completed(futures), desc='Extraindo espelhos', ncols=60, total=len(df)):
            try:
                future.result()
            except Exception as e:
                id_peca = futures[future]
                registrar_log_inconsistencia(id_peca, 'EXCECAO_THREAD', cfg, str(e)[:200])
                print(f'Erro ao processar peça id_peca={id_peca}: {traceback.format_exc()}')
    print_sessao()

    # resumo dos arquivos gerados
    lst = UtilArquivos.listar_arquivos(cfg['pasta_saidas'], mascara='*.json')
    lst = [arq for arq in lst if '.resumo.' not in arq]
    print('\n' + '='*80)
    print(f'ARQUIVOS GERADOS: {cfg["pasta_saidas"]}')
    print(f' - Total de arquivos: {len(lst)}')
    print(f' - Total de peças analisadas: {len(df)}')
    print('='*80)

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
    # [TAG: EXTRACTION_AGENT_MODELS]
    # Como usar: configure os pares (pasta, modelo) desejados na lista abaixo.
    # O prefixo "or:" indica para a classe usar o openrouter.ai.
    # rodada completa para todos os modelos do experimento
    lista_modelo_pasta = [
        ('espelhos_agentes_gpt5', 'or:openai/gpt-5'),
        ('espelhos_agentes_gemma3_12b', 'or:google/gemma-3-12b-it'),
        ('espelhos_agentes_gemma3_27b', 'or:google/gemma-3-27b-it')
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
