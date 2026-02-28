# -*- coding: utf-8 -*-
"""
Orquestrador de agentes especializados para extração de espelhos de acórdãos.

Autor: Luiz Anísio
Fonte: https://github.com/luizanisio/llms/tree/main/experimentos/agentes-esp-acordao
Data: 14/11/2025

Descrição:
-----------
Implementa sistema de agentes especializados que trabalham em pipeline para extrair
informações estruturadas de acórdãos jurídicos: teses, jurisprudências citadas,
referências legislativas, notas, temas, etc. Inclui validação final e mecanismo
de revisão com observabilidade completa do processo.
"""

import sys
sys.path.append('../prompts')
from prompt_espelho_agentes import *


from glob import glob
import os
import json
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

MAXIMO_ITERACOES = 5

# Mapeamento de tags de campos para nomes de agentes
MAPEAMENTO_TAGS_AGENTES = {
    '#teseJuridica': 'AgenteTeses',
    '#JuCi': 'AgenteJurisprudenciasCitadas',
    '#RefLeg': 'AgenteReferenciasLegislativas',
    '#ICE': 'AgenteInformacoesComplementares',
    '#TAP': 'AgenteTermosAuxiliares',
    '#notas': 'AgenteNotas',
    '#tema': 'AgenteTema'
}

'''
Pipeline de execução:
1. AgenteCampos - identifica campos necessários
2. AgenteTeses - extrai teses (dependência: nenhuma)
3. AgenteJurisprudenciasCitadas - extrai jurisprudências com dependência das teses extraídas
4. Agentes em paralelo:
    - AgenteNotas
    - AgenteInformacoesComplementares
    - AgenteTermosAuxiliares
    - AgenteTema
    - AgenteReferenciasLegislativas
5. AgenteValidacaoFinal - valida e coordena revisões
6. Loop de revisão conforme necessário
7. O orquestrador compila o espelho final e gera relatórios de observabilidade
8. Arquivo final é salvo na pasta de extração informada
'''

class Agente():
    def __init__(self, nome:str, prompt_base: str, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        if not modelo:
            raise ValueError(f"Parâmetro 'modelo' é obrigatório para o agente {nome}")
        self.nome = nome
        self.prompt_base = prompt_base
        self.modelo = modelo
        self.modelo_think = modelo_think
        self.resposta = None
        self.iteracoes = 0
        self.erros_consecutivos = 0  # Contador de erros que não consomem iterações
        self.maximo_iteracoes = maximo_iteracoes
        self.texto = None
        self.revisao = None
        self.historico_execucoes = []
        
    def preparar_prompt(self, texto: str, revisao: str = None, **kwargs) -> str:
        ''' Prepara o prompt completo com texto e revisão quando houver.
            Subclasses podem estender este método para aceitar kwargs adicionais.
        '''
        prompt = self.prompt_base
        _texto = texto.strip(" \t\n")
        prompt += f'\n<TEXTO>\n{_texto}\n</TEXTO>'
        
        # Sempre inclui tag <REVISAO> para consistência (vazia se não houver revisão)
        if revisao:
            prompt += f'\n\n<REVISAO>\n{revisao}\n</REVISAO>'
        else:
            prompt += f'\n\n<REVISAO> \n</REVISAO>'
            
        if self.nome == 'AgenteValidacaoFinal':
            prompt += f'\n\n<ESTADO_VALIDACAO>\nIteração Atual: {self.iteracoes + 1}\nMáximo Iterações: {self.maximo_iteracoes}\n</ESTADO_VALIDACAO>'
            
        if '<--INICIO_TOLERANCIA-->' in prompt:
            # Tolerância inicia na última iteração para evitar loop infinito
            prompt = prompt.replace('<--INICIO_TOLERANCIA-->', str(self.maximo_iteracoes))
            
        return prompt
        
    def executar(self, texto: str, revisao: str = None, callable_modelo = None, contexto_adicional: dict = None):
        ''' Executa o agente conforme o prompt base e o modelo configurados.
            Inclui dados de revisão quando solicitado.
            Acrescenta iterações até o máximo permitido.
            Se atingir o máximo de iterações, retorna na chave "contribuição" uma mensagem 
            informando o limite atingido e não executa o prompt.
            Caso contrário, executa o prompt e armazena a resposta.
            
            IMPORTANTE: Erros de execução NÃO consomem iterações.
            O contador self.iteracoes só é incrementado após execução bem-sucedida.
            Um contador separado self.erros_consecutivos evita retry infinito.
            
            Args:
                texto (str): Texto do acórdão a ser processado
                revisao (str, optional): Instruções de revisão do agente validador
                callable_modelo (callable, optional): Função para chamar o modelo
                contexto_adicional (dict, optional): Contexto adicional para preparar_prompt
            
            Returns:
                dict: Resposta do agente em formato JSON ou dict com erro
        '''
        inicio = datetime.now()
        self.texto = texto
        self.revisao = revisao
        
        # Verifica se atingiu o máximo de iterações BEM-SUCEDIDAS
        if self.iteracoes >= self.maximo_iteracoes:
            if self.resposta:
               return self.resposta
               
            resultado = {
                "contribuição": f"Limite de {self.maximo_iteracoes} iterações atingido sem sucesso",
                "erro": "maximo_iteracoes_atingido"
            }
            self.resposta = resultado
            self.historico_execucoes.append({
                'iteracao': self.iteracoes,
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'resultado': 'limite_atingido',
                'resposta': resultado
            })
            return resultado
        
        # Verifica se há muitos erros consecutivos (evita retry infinito)
        max_erros_consecutivos = 3
        if self.erros_consecutivos >= max_erros_consecutivos:
            resultado = {
                "contribuição": f"Limite de {max_erros_consecutivos} erros consecutivos atingido",
                "erro": "maximo_erros_consecutivos"
            }
            self.resposta = resultado
            self.historico_execucoes.append({
                'iteracao': self.iteracoes,
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'resultado': 'limite_erros',
                'resposta': resultado
            })
            return resultado
        
        # Prepara o prompt completo
        prompt_completo = self.preparar_prompt(texto, revisao, contexto_adicional=contexto_adicional)
        
        # Valida que callable_modelo foi fornecido
        if not callable_modelo:
            raise ValueError(f"Parâmetro 'callable_modelo' é obrigatório para executar o agente {self.nome}")
        
        # Chama o modelo
        try:
            resposta = callable_modelo(prompt_completo, modelo=self.modelo, modelo_think=self.modelo_think, as_json=True)
            
            # get_resposta já retorna dict com 'resposta' parseado
            # Não é necessário parsear novamente
            self.resposta = resposta
            
            # Execução bem-sucedida: incrementa iterações e reseta erros consecutivos
            self.iteracoes += 1
            self.erros_consecutivos = 0
            
            # Registra no histórico
            self.historico_execucoes.append({
                'iteracao': self.iteracoes,
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'resultado': 'sucesso',
                'tem_revisao': bool(revisao),
                'resposta': resposta
            })
            
            return resposta
            
        except Exception as e:
            # Erro: NÃO incrementa iterações, mas incrementa erros consecutivos
            self.erros_consecutivos += 1
            
            resultado = {
                "contribuição": f"Erro na execução do agente: {str(e)}",
                "erro": "exception",
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "erros_consecutivos": self.erros_consecutivos
            }
            self.resposta = resultado
            
            self.historico_execucoes.append({
                'iteracao': self.iteracoes,  # Não incrementado - erro não conta
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'resultado': 'erro',
                'tem_revisao': bool(revisao),
                'erros_consecutivos': self.erros_consecutivos,
                'resposta': resultado
            })
            
            return resultado
        
    def get_resposta(self) -> dict:
        ''' Retorna a resposta mais recente do agente.
        '''
        return self.resposta
    
    def get_historico(self) -> list:
        ''' Retorna o histórico de todas as execuções do agente.
        '''
        return self.historico_execucoes
    
    def resetar(self):
        ''' Reseta o estado do agente para nova execução.
        '''
        self.resposta = None
        self.iteracoes = 0
        self.erros_consecutivos = 0
        self.texto = None
        self.revisao = None
        self.historico_execucoes = []
        
        
# ==================== Agentes Especializados ====================

class AgenteCampos(Agente):
    ''' Agente responsável por identificar quais campos devem ser extraídos do acórdão. '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteCampos', PROMPT_AGENTE_CAMPOS, modelo, modelo_think, maximo_iteracoes)

class AgenteTeses(Agente):
    ''' Agente responsável por extrair as teses jurídicas do acórdão. '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteTeses', PROMPT_AGENTE_TESES, modelo, modelo_think, maximo_iteracoes)

class AgenteJurisprudenciasCitadas(Agente):
    ''' Agente responsável por extrair as jurisprudências citadas no acórdão. '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteJurisprudenciasCitadas', PROMPT_AGENTE_JURIS_CITADA, modelo, modelo_think, maximo_iteracoes)
    
    def preparar_prompt(self, texto: str, revisao: str = None, contexto_adicional: dict = None, **kwargs) -> str:
        ''' Prepara o prompt incluindo as teses extraídas pelo AgenteTeses.
        '''
        prompt = self.prompt_base
        _texto = texto.strip(" \t\n")
        prompt += f'\n<TEXTO>\n{_texto}\n</TEXTO>'
        
        # Inclui as teses extraídas como contexto
        # contexto_adicional substitui o antigo contexto_teses
        if contexto_adicional:
            teses_json = json.dumps(contexto_adicional, ensure_ascii=False, indent=2)
            prompt += f'\n\n<TESES>\n{teses_json}\n</TESES>'
        
        # Sempre inclui tag <REVISAO> para consistência (vazia se não houver revisão)
        if revisao:
            prompt += f'\n\n<REVISAO>\n{revisao}\n</REVISAO>'
        else:
            prompt += f'\n\n<REVISAO>\n</REVISAO>'
        
        return prompt

class AgenteReferenciasLegislativas(Agente):
    ''' Agente responsável por extrair as referências legislativas do acórdão. '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteReferenciasLegislativas', PROMPT_AGENTE_REF_LEG, modelo, modelo_think, maximo_iteracoes)

class AgenteNotas(Agente):
    ''' Agente responsável por extrair as notas temáticas do acórdão. '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteNotas', PROMPT_AGENTE_NOTAS, modelo, modelo_think, maximo_iteracoes)

class AgenteInformacoesComplementares(Agente):
    ''' Agente responsável por extrair informações complementares à ementa (ICE). '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteInformacoesComplementares', PROMPT_AGENTE_INF_COMPL_EMENTA, modelo, modelo_think, maximo_iteracoes)

class AgenteTermosAuxiliares(Agente):
    ''' Agente responsável por gerar termos auxiliares à pesquisa (TAP). '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteTermosAuxiliares', PROMPT_AGENTE_TERMOS_AUX_PESQUISA, modelo, modelo_think, maximo_iteracoes)

class AgenteTema(Agente):
    ''' Agente responsável por identificar temas de repercussão geral e recursos repetitivos. '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteTema', PROMPT_AGENTE_TEMA, modelo, modelo_think, maximo_iteracoes)

class AgenteValidacaoFinal(Agente):
    ''' Agente responsável pela validação final e coordenação de revisões. '''
    def __init__(self, modelo: str, modelo_think: str = None, maximo_iteracoes: int = MAXIMO_ITERACOES):
        super().__init__('AgenteValidacaoFinal', PROMPT_VALIDACAO_FINAL, modelo, modelo_think, maximo_iteracoes)
    
    def preparar_prompt(self, texto: str, saidas_agentes: dict = None) -> str:
        ''' Prepara o prompt do validador incluindo as saídas dos outros agentes.
        '''
        prompt = self.prompt_base
        
        # saidas_agentes pode ser um dict com estrutura {saidas: {...}, campos_aprovados: [...]}
        # ou um dict simples de saídas (compatibilidade retroativa)
        campos_aprovados = []
        saidas = saidas_agentes
        
        if isinstance(saidas_agentes, dict):
            if 'saidas' in saidas_agentes:
                saidas = saidas_agentes.get('saidas', {})
                campos_aprovados = saidas_agentes.get('campos_aprovados', [])
        
        # Inclui as saídas dos agentes para validação
        if saidas:
            saidas_json = json.dumps(saidas, ensure_ascii=False, indent=2)
            # Substitui ou adiciona as saídas antes do texto
            saidas_txt = f'<SAIDAS_PARCIAIS>\n{saidas_json}\n</SAIDAS_PARCIAIS>'
        else:
            saidas_txt = '<SAIDAS_PARCIAIS>\n{ }\n</SAIDAS_PARCIAIS>'
        
        # Adiciona lista de campos já aprovados (não devem gerar novas revisões)
        if campos_aprovados:
            campos_txt = f'\n<CAMPOS_JA_APROVADOS>\nOs seguintes campos já foram aprovados em iterações anteriores e NÃO DEVEM ser incluídos no dicionário "revisao":\n{", ".join(campos_aprovados)}\n</CAMPOS_JA_APROVADOS>\n'
        else:
            campos_txt = ''
        
        # Adiciona o texto original (contexto mínimo para validações)
        _texto = texto.strip(" \t\n")
        prompt += f'\n<TEXTO>\n{_texto}\n</TEXTO>\n'
        prompt += f'\n{saidas_txt}\n'
        prompt += campos_txt
        
        # Prepara mensagem de estado da validação
        is_ultima_iteracao = (self.iteracoes + 1) >= self.maximo_iteracoes
        
        msg_status = f'\n<ESTADO_VALIDACAO>\nIteração Atual: {self.iteracoes + 1}\nMáximo Iterações: {self.maximo_iteracoes}\n'
        
        if is_ultima_iteracao:
            msg_status += '''
⚠️ ATENÇÃO: MODO DE TOLERÂNCIA MÁXIMA ATIVADO ⚠️
Você está na ÚLTIMA TENTATIVA. O objetivo agora é ENCERRAR O PROCESSO para evitar loop infinito.
1. APROVE a validação (validacao_aprovada: true) se o JSON estiver válido e não houver alucinações graves.
2. IGNORE erros menores de formatação, estilo, pontuação ou precisão de termos.
3. SÓ REJEITE se o resultado for COMPLETAMENTE INUTILIZÁVEL (ex: JSON quebrado, campos obrigatórios vazios).
'''
        msg_status += '</ESTADO_VALIDACAO>\n'
        
        # Injeta no local apropriado (placeholder) ou no final
        if '<--STATUS_REVISAO-->' in prompt:
            prompt = prompt.replace('<--STATUS_REVISAO-->', msg_status)
        else:
            prompt += f'\n{msg_status}'
        
        # Remove placeholder antigo de tolerância se ainda existir (limpeza legacy)
        if '<--INICIO_TOLERANCIA-->' in prompt:
            prompt = prompt.replace('<--INICIO_TOLERANCIA-->', str(self.maximo_iteracoes))
        
        return prompt
    
    def executar(self, texto: str, saidas_agentes: dict = None, callable_modelo = None):
        ''' Executa o validador com as saídas dos agentes especializados.
        '''
        inicio = datetime.now()
        self.texto = texto
        
        # Verifica se atingiu limite ANTES de incrementar
        if self.iteracoes >= self.maximo_iteracoes:
            # Se já temos uma resposta anterior, preserva ela!
            # Atingir o limite não deve descartar o trabalho feito.
            if self.resposta:
                self._registrar_log(f"Limite de iterações atingido ({self.maximo_iteracoes}). Mantendo última resposta válida.")
                return self.resposta
                
            resultado = {
                "contribuição": f"Limite de {self.maximo_iteracoes} iterações de validação atingido",
                "erro": "maximo_iteracoes_atingido"
            }
            self.resposta = resultado # Só sobrescreve se não tinha nada
            self.historico_execucoes.append({
                'iteracao': self.iteracoes,
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'resultado': 'limite_atingido',
                'resposta': resultado
            })
            return resultado
        
        # Prepara prompt (note que iteracoes ainda é o valor antigo, então +1 para mostrar a atual)
        prompt_completo = self.preparar_prompt(texto, saidas_agentes)
        
        # Valida que callable_modelo foi fornecido
        if not callable_modelo:
            raise ValueError(f"Parâmetro 'callable_modelo' é obrigatório para executar o agente {self.nome}")
        
        try:
            resposta = callable_modelo(prompt_completo, modelo=self.modelo, modelo_think=self.modelo_think, as_json=True)
            
            self.resposta = resposta
            
            # Incrementa APÓS sucesso
            self.iteracoes += 1
            
            self.historico_execucoes.append({
                'iteracao': self.iteracoes,
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'resultado': 'sucesso',
                'resposta': resposta
            })
            
            return resposta
            
        except Exception as e:
            # Em caso de erro, NÃO incrementa iteração
            resultado = {
                "contribuição": f"Erro na validação: {str(e)}",
                "erro": "exception",
                "exception_type": type(e).__name__,
                "exception_message": str(e)
            }
            self.resposta = resultado
            
            self.historico_execucoes.append({
                'iteracao': self.iteracoes, # Mantém iteração anterior pois falhou
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'resultado': 'erro',
                'resposta': resultado
            })
            
            return resultado

##################################################################
# ==================== Orquestrador Principal ====================
##################################################################
class AgenteOrquestradorEspelho():
    ''' Orquestrador responsável por coordenar a execução dos agentes especializados
        para extração completa do espelho do acórdão.
        
        Args:
            id_peca: ID da peça a ser processada
            texto_peca: Texto completo do acórdão
            modelo_espelho: Modelo de linguagem a ser utilizado (obrigatório)
            modelo_think: Modo de pensamento do modelo (opcional)
            callable_modelo: Função callable para executar chamadas ao modelo (obrigatório)
            observabilidade: Se True, ativa coleta de dados de observabilidade
            pasta_extracao: Pasta onde os espelhos extraídos serão salvos
            - <pasta_extracao>/observabilidade: Pasta para gravar arquivos de observabilidade se observabilidade=True
    '''
    def __init__(self, id_peca: str = None, texto_peca: str = None, 
                 modelo_espelho: str = None, modelo_think: str = None,
                 callable_modelo = None,
                 pasta_extracao: str = None, observabilidade: bool = False,
                 ignorar_se_existir: bool = True):
        if not modelo_espelho:
            raise ValueError("Parâmetro 'modelo_espelho' é obrigatório")
        if (not callable_modelo) or not callable(callable_modelo):
            raise ValueError("Parâmetro 'callable_modelo' é obrigatório e deve ser um método")
        
        self.id_peca = id_peca
        self.texto_peca = texto_peca
        self.modelo_espelho = modelo_espelho
        self.modelo_think = modelo_think
        self.callable_modelo = callable_modelo
        self.ignorar_se_existir = ignorar_se_existir
        self._lock_observabilidade = Lock()
        self._lock_arquivo = Lock()  # Lock específico para escrita em arquivo
        self.observabilidade = {}
        self.log = []
        self.pasta_extracao = pasta_extracao
        self.pasta_observabilidade = os.path.join(pasta_extracao, 'observabilidade') if observabilidade else None
        
        # Define nomes dos arquivos de saída
        self.arquivo_resultado = os.path.join(pasta_extracao, f'{id_peca}.json') if id_peca else None
        self.arquivo_resumo = os.path.join(pasta_extracao, f'{id_peca}.resumo.json') if id_peca else None
        
        assert self.pasta_extracao is not None, "pasta_extracao deve ser informada"
        assert self.id_peca is not None, "id_peca deve ser informado"
        # Cria a pasta de extração se não existir
        if self.pasta_extracao and not os.path.exists(self.pasta_extracao):
            os.makedirs(self.pasta_extracao, exist_ok=True)
        if not os.path.isdir(self.pasta_extracao):
            raise ValueError(f"pasta_extracao '{self.pasta_extracao}' não é um diretório válido")
        if self.pasta_observabilidade and not os.path.exists(self.pasta_observabilidade):
            os.makedirs(self.pasta_observabilidade, exist_ok=True)
        
        # Mapeamento dos agentes disponíveis
        self._agentes_disponiveis = {
            'AgenteCampos': AgenteCampos,
            'AgenteTeses': AgenteTeses,
            'AgenteJurisprudenciasCitadas': AgenteJurisprudenciasCitadas,
            'AgenteReferenciasLegislativas': AgenteReferenciasLegislativas,
            'AgenteNotas': AgenteNotas,
            'AgenteInformacoesComplementares': AgenteInformacoesComplementares,
            'AgenteTermosAuxiliares': AgenteTermosAuxiliares,
            'AgenteTema': AgenteTema,
            'AgenteValidacaoFinal': AgenteValidacaoFinal
        }
        
        # Instâncias dos agentes
        self._agentes_instancias = {}
        
        # Resultados das extrações
        self.resultados = {}
        
        # Campos identificados para extração
        self._campos_para_extrair = set()
        
        # Campos já aprovados pelo validador (não devem ser revisados novamente)
        self._campos_aprovados = set()
        
        # Últimas instruções de revisão enviadas a cada agente (para "memória" do validador)
        self._ultimas_revisoes = {}
    
    def _criar_agente(self, nome_agente: str) -> Agente:
        ''' Cria uma instância do agente especificado.
        '''
        if nome_agente not in self._agentes_disponiveis:
            raise ValueError(f"Agente '{nome_agente}' não encontrado")
        
        classe_agente = self._agentes_disponiveis[nome_agente]
        return classe_agente(modelo=self.modelo_espelho, modelo_think=self.modelo_think)
    
    def _soma_observabilidade(self, tipo: str, dados: dict = None):
        ''' Registra dados de observabilidade para o tipo/campo informado.
            Se pasta_observabilidade estiver definida, grava em arquivo.
        '''
        if not isinstance(dados, dict):
            return False
        with self._lock_observabilidade:
            if tipo not in self.observabilidade:
                self.observabilidade[tipo] = [dados]
            else:
                self.observabilidade[tipo].append(dados)
        
        # Grava arquivo de observabilidade se pasta estiver definida
        self._gravar_observabilidade()
        
        return True
    
    def _gravar_observabilidade(self):
        ''' Grava o arquivo de observabilidade de forma thread-safe.
        '''
        if not self.pasta_observabilidade or not self.id_peca:
            return
        
        try:
            with self._lock_arquivo:
                arquivo_obs = os.path.join(self.pasta_observabilidade, f'{self.id_peca}.obs.json')
                
                # Prepara dados para gravação
                dados_completos = {
                    'id_peca': self.id_peca,
                    'timestamp_atualizacao': datetime.now().isoformat(),
                    'observabilidade': self.observabilidade,
                    'log': self.log
                }
                
                # Grava arquivo com identação
                with open(arquivo_obs, 'w', encoding='utf-8') as f:
                    json.dump(dados_completos, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # Não falha se não conseguir gravar
            self._registrar_log(f"Erro ao gravar observabilidade: {str(e)}", 'warning')
    
    def _registrar_log(self, mensagem: str, nivel: str = 'info'):
        ''' Registra mensagem no log do orquestrador.
            Se pasta_observabilidade estiver definida, atualiza o arquivo.
        '''
        entrada_log = {
            'timestamp': datetime.now().isoformat(),
            'nivel': nivel,
            'mensagem': mensagem
        }
        self.log.append(entrada_log)
        
        # Atualiza arquivo de observabilidade com novo log
        # Não chama _gravar_observabilidade() diretamente para evitar gravações excessivas
        # O arquivo será atualizado na próxima chamada de _soma_observabilidade()
    
    def _limpar_resposta_para_validacao(self, resposta: dict) -> dict:
        ''' Remove chaves desnecessárias da resposta para enviar ao validador.
            Economiza tokens e reduz ruído.
        '''
        if not isinstance(resposta, dict):
            return resposta
        
        # Chaves que não precisam ir para o validador
        chaves_remover = ['contribuição', 'contribuicao', 'usage', 'model', 'tempo', 'json']
        
        resposta_limpa = {}
        for chave, valor in resposta.items():
            if chave.lower() not in [c.lower() for c in chaves_remover]:
                resposta_limpa[chave] = valor
        
        return resposta_limpa
    
    def _gravar_prompt(self, nome_agente: str, prompt_completo: str, iteracao: int = 1):
        ''' Grava o prompt completo em arquivo texto de forma thread-safe.
            Primeira iteração: cria arquivo. Iterações seguintes: append.
        '''
        if not self.pasta_observabilidade or not self.id_peca:
            return
        
        try:
            with self._lock_arquivo:
                # Nome do arquivo sempre sem indicador de iteração
                nome_arquivo = f'{self.id_peca}.{nome_agente}.txt'
                arquivo_prompt = os.path.join(self.pasta_observabilidade, nome_arquivo)
                
                # Trata modelo_think None
                modelo_think_str = str(self.modelo_think) if self.modelo_think else 'None'
                
                if iteracao == 1:
                    # Primeira iteração: cria o arquivo
                    with open(arquivo_prompt, 'w', encoding='utf-8') as f:
                        f.write(f"# Prompt para {nome_agente}\n")
                        f.write(f"# ID Peça: {self.id_peca}\n")
                        f.write(f"# Iteração: {iteracao}\n")
                        f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
                        f.write(f"# Modelo: {self.modelo_espelho}\n")
                        f.write(f"# Think: {modelo_think_str}\n")
                        f.write("\n" + "=" * 80 + "\n")
                        f.write("PROMPT ENVIADO\n")
                        f.write("=" * 80 + "\n\n")
                        f.write(prompt_completo)
                else:
                    # Iterações seguintes: append com separador
                    with open(arquivo_prompt, 'a', encoding='utf-8') as f:
                        f.write("\n\n")
                        f.write("#" * 80 + "\n")
                        f.write(f"# ITERAÇÃO {iteracao} - PROMPT DE REVISÃO\n")
                        f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
                        f.write("#" * 80 + "\n")
                        f.write("PROMPT ENVIADO\n")
                        f.write("=" * 80 + "\n\n")
                        f.write(prompt_completo)
                
                self._registrar_log(f"Prompt gravado: {nome_arquivo} (iteração {iteracao})")
                
                # Retorna o caminho do arquivo para uso posterior
                return arquivo_prompt
        except Exception as e:
            self._registrar_log(f"Erro ao gravar prompt de {nome_agente}: {str(e)}", 'warning')
            return None
    
    def _gravar_resposta(self, nome_agente: str, resposta: dict, iteracao: int = 1, revisao: str = None):
        ''' Grava a resposta do agente no mesmo arquivo do prompt com append (thread-safe).
            Para iterações > 1, grava no arquivo original com separadores de iteração.
        '''
        if (not self.pasta_observabilidade) or (not self.id_peca):
            return
        
        try:
            with self._lock_arquivo:
                # Nome do arquivo sempre usa o nome base (primeira iteração)
                nome_arquivo = f'{self.id_peca}.{nome_agente}.txt'
                arquivo_prompt = os.path.join(self.pasta_observabilidade, nome_arquivo)
                
                # Append da resposta/revisão no arquivo
                with open(arquivo_prompt, 'a', encoding='utf-8') as f:
                    # Se for iteração > 1, adiciona separador de revisão
                    if iteracao > 1:
                        f.write("\n\n")
                        f.write("#" * 80 + "\n")
                        f.write(f"# ITERAÇÃO {iteracao} - REVISÃO\n")
                        f.write("#" * 80 + "\n")
                        if revisao:
                            # Trata revisao None
                            revisao_str = str(revisao) if revisao else '(vazia)'
                            f.write(f"# Solicitação de Revisão:\n")
                            f.write(f"# {revisao_str}\n")
                        f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
                        f.write("#" * 80 + "\n")
                    else:
                        f.write("\n\n")
                        f.write("=" * 80 + "\n")
                        f.write("RESPOSTA RECEBIDA\n")
                        f.write("=" * 80 + "\n")
                        f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
                    
                    f.write("\n")
                    # Grava a resposta em JSON formatado
                    f.write(json.dumps(resposta, ensure_ascii=False, indent=2))
                                    
                self._registrar_log(f"Resposta gravada: {nome_arquivo} (iteração {iteracao})")
        except Exception as e:
            self._registrar_log(f"Erro ao gravar resposta de {nome_agente}: {str(e)}", 'warning')
    
    def _executar_agente_unico(self, nome_agente: str, revisao: str = None, contexto_adicional: dict = None) -> dict:
        ''' Executa um único agente e registra observabilidade.
        '''
        inicio = datetime.now()
        self._registrar_log(f"Iniciando execução do agente: {nome_agente}")
        
        try:
            # Cria ou recupera instância do agente
            if nome_agente not in self._agentes_instancias:
                self._agentes_instancias[nome_agente] = self._criar_agente(nome_agente)
            
            agente = self._agentes_instancias[nome_agente]
            
            # Prepara o prompt completo antes da execução (para gravação de log)
            if nome_agente == 'AgenteValidacaoFinal':
                prompt_completo = agente.preparar_prompt(texto=self.texto_peca, saidas_agentes=contexto_adicional)
            elif nome_agente == 'AgenteJurisprudenciasCitadas' and contexto_adicional:
                prompt_completo = agente.preparar_prompt(texto=self.texto_peca, revisao=revisao, contexto_adicional=contexto_adicional)
            else:
                prompt_completo = agente.preparar_prompt(texto=self.texto_peca, revisao=revisao)
            
            # Grava o prompt se configurado (APENAS na primeira iteração)
            self._gravar_prompt(nome_agente, prompt_completo, agente.iteracoes + 1)
            
            # Executa o agente com callable_modelo
            # 🔧 CORREÇÃO: Passar contexto_adicional para TODOS os agentes (não apenas validador)
            if nome_agente == 'AgenteValidacaoFinal':
                resposta = agente.executar(texto=self.texto_peca, saidas_agentes=contexto_adicional, callable_modelo=self.callable_modelo)
            else:
                # Passa contexto_adicional para todos os agentes (incluindo AgenteJurisprudenciasCitadas)
                resposta = agente.executar(texto=self.texto_peca, revisao=revisao, callable_modelo=self.callable_modelo, contexto_adicional=contexto_adicional)
            
            # Grava a resposta se configurado (com informação de revisão se houver)
            self._gravar_resposta(nome_agente, resposta, agente.iteracoes, revisao)
            
            # Registra observabilidade
            duracao = (datetime.now() - inicio).total_seconds()
            dados_obs = {
                'agente': nome_agente,
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': duracao,
                'iteracoes': agente.iteracoes,
                'tem_revisao': bool(revisao),
                'sucesso': 'erro' not in resposta,
                'resposta_keys': list(resposta.keys()) if isinstance(resposta, dict) else [],
                'resposta': resposta  # Incluindo resposta completa para extrair tokens depois
            }
            self._soma_observabilidade(nome_agente, dados_obs)
            
            self._registrar_log(f"Agente {nome_agente} concluído em {duracao:.2f}s")
            
            return resposta
            
        except Exception as e:
            self._registrar_log(f"Erro ao executar agente {nome_agente}: {str(e)}", 'error')
            erro_resposta = {
                'contribuição': f'Erro na execução: {str(e)}',
                'erro': 'exception',
                'agente': nome_agente
            }
            
            # Grava a resposta de erro se configurado
            if nome_agente in self._agentes_instancias:
                agente = self._agentes_instancias[nome_agente]
                self._gravar_resposta(nome_agente, erro_resposta, agente.iteracoes, revisao)
            
            # Registra erro na observabilidade
            dados_obs = {
                'agente': nome_agente,
                'inicio': inicio.isoformat(),
                'fim': datetime.now().isoformat(),
                'duracao_segundos': (datetime.now() - inicio).total_seconds(),
                'sucesso': False,
                'erro': str(e),
                'resposta': erro_resposta  # Incluindo resposta de erro completa
            }
            self._soma_observabilidade(nome_agente, dados_obs)
            
            return erro_resposta
    
    def _executar_agentes_paralelo(self, nomes_agentes: list) -> dict:
        ''' Executa múltiplos agentes em paralelo usando ThreadPool.
        '''
        self._registrar_log(f"Executando {len(nomes_agentes)} agentes em paralelo: {', '.join(nomes_agentes)}")
        
        resultados_parciais = {}
        
        with ThreadPoolExecutor(max_workers=len(nomes_agentes)) as executor:
            # Submete todas as tarefas
            futuro_para_agente = {
                executor.submit(self._executar_agente_unico, nome): nome
                for nome in nomes_agentes
            }
            
            # Coleta resultados conforme completam
            for futuro in as_completed(futuro_para_agente):
                nome_agente = futuro_para_agente[futuro]
                try:
                    resultado = futuro.result()
                    resultados_parciais[nome_agente] = resultado
                except Exception as e:
                    self._registrar_log(f"Exceção ao processar futuro de {nome_agente}: {str(e)}", 'error')
                    resultados_parciais[nome_agente] = {
                        'contribuição': f'Erro no thread pool: {str(e)}',
                        'erro': 'thread_exception'
                    }
        
        return resultados_parciais
    
    def _extrair_campos_necessarios(self, resposta_campos: dict) -> set:
        ''' Extrai os nomes dos campos que precisam ser processados a partir da resposta do AgenteCampos.
        '''
        campos = set()
        
        # Tenta extrair diretamente do caminho esperado: resposta_campos['resposta']['campos']
        texto_resposta = ''
        
        if isinstance(resposta_campos, dict):
            # A resposta do modelo geralmente vem dentro de 'resposta' -> 'campos'
            # Mas às vezes o wrapper já entregou o json parseado no nível raiz
            resposta_agente = resposta_campos.get('resposta', resposta_campos)
            
            if isinstance(resposta_agente, dict):
                texto_resposta = resposta_agente.get('campos', '')
        
        # Converte para string (pode vir como lista de strings)
        texto_resposta = str(texto_resposta)
        
        if not isinstance(texto_resposta, str):
            texto_resposta = str(texto_resposta)
        
        # Log para debug
        self._registrar_log(f"Texto extraído do AgenteCampos (primeiros 500 chars): {texto_resposta[:500]}")
        
        # Extrai tags #campo do texto (usando constante)
        for tag, agente in MAPEAMENTO_TAGS_AGENTES.items():
            if tag in texto_resposta:
                campos.add(agente)
                self._registrar_log(f"Tag '{tag}' encontrada -> Agente '{agente}'")
        
        if not campos:
            self._registrar_log("AVISO: Nenhum campo identificado! Estrutura da resposta pode estar incorreta.", 'warning')
            self._registrar_log(f"Resposta completa do AgenteCampos: {resposta_campos}", 'warning')
        
        self._registrar_log(f"Campos identificados para extração: {', '.join(campos) if campos else 'NENHUM'}")
        
        return campos
    
    def _processar_revisao(self, resposta_validacao: dict) -> dict:
        ''' Processa as instruções de revisão do validador e reexecuta agentes necessários.
            Retorna True se validação foi aprovada, False caso contrário.
        '''
        # Extrai revisão da resposta do validador
        resposta_agente = resposta_validacao.get('resposta', {})
        if isinstance(resposta_agente, dict):
            revisao = resposta_agente.get('revisao', {})
            validacao_aprovada = resposta_agente.get('validacao_aprovada', False)
        else:
            revisao = {}
            validacao_aprovada = False
        
        # PRIORIDADE 1: Se houver revisão, processa a revisão (mesmo que validacao_aprovada venha como True)
        # O fato de existir instrução de correção prevalece sobre o flag booleano
        if revisao and len(revisao) > 0:
            if validacao_aprovada:
                self._registrar_log("AVISO: Validação marcada como aprovada mas contém instruções de revisão. Processando revisão.", 'warning')
                validacao_aprovada = False # Força False para continuar o fluxo
        
        # Se validação aprovada E não há revisão, encerra
        if validacao_aprovada:
            self._registrar_log("Validação aprovada - nenhuma revisão necessária")
            return True
        
        # Se não foi aprovada, mas também não há instruções de revisão, algo está errado
        if not validacao_aprovada and (not revisao or len(revisao) == 0):
            self._registrar_log("AVISO: Validação não aprovada mas sem instruções de revisão", 'warning')
            return False
        
        self._registrar_log(f"Processando revisões para {len(revisao)} agentes: {', '.join(revisao.keys())}")
        
        # Atualiza lista de campos aprovados: campos não mencionados na revisão são aprovados
        # Considera apenas agentes de extração (não AgenteCampos nem AgenteValidacaoFinal)
        agentes_extracao = set(self._agentes_disponiveis.keys()) - {'AgenteCampos', 'AgenteValidacaoFinal'}
        for agente in agentes_extracao:
            if agente in self.resultados and agente not in revisao:
                if agente not in self._campos_aprovados:
                    self._registrar_log(f"Campo '{agente}' aprovado pelo validador (não requer revisão)")
                    self._campos_aprovados.add(agente)
        
        # A revisão agora vem com nomes de agentes diretamente (AgenteTeses, AgenteJurisprudenciasCitadas, etc)
        # Não é mais necessário mapear campos para agentes
        
        # Prepara a ordem de execução das revisões
        # AgenteTeses deve ser o primeiro pois AgenteJurisprudenciasCitadas depende dele
        agentes_ordenados = list(revisao.keys())
        if 'AgenteTeses' in agentes_ordenados:
            agentes_ordenados.remove('AgenteTeses')
            agentes_ordenados.insert(0, 'AgenteTeses')
            
        self._registrar_log(f"Ordem de execução das revisões: {', '.join(agentes_ordenados)}")

        # Reexecuta agentes com revisão
        for nome_agente in agentes_ordenados:
            instrucao_revisao = revisao[nome_agente]
            # Valida se o nome do agente é válido
            if nome_agente not in self._agentes_disponiveis:
                self._registrar_log(f"Agente '{nome_agente}' não reconhecido - ignorando", 'warning')
                continue
            
            # Trata instrucao_revisao None ou vazia
            instrucao_preview = ''
            if instrucao_revisao:
                instrucao_str = str(instrucao_revisao)
                instrucao_preview = instrucao_str[:100] if len(instrucao_str) > 100 else instrucao_str
            else:
                instrucao_preview = '(vazia)'
            
            self._registrar_log(f"Reexecutando {nome_agente} com revisão: {instrucao_preview}...")
            
            # Armazena a instrução de revisão para enviar ao validador na próxima iteração
            self._ultimas_revisoes[nome_agente] = instrucao_revisao
            
            # Se for AgenteJurisprudenciasCitadas, precisa passar o contexto das teses
            if nome_agente == 'AgenteJurisprudenciasCitadas':
                contexto_teses = self.resultados.get('AgenteTeses', {}).get('resposta', {})
                resultado_revisado = self._executar_agente_unico(nome_agente, revisao=instrucao_revisao, contexto_adicional=contexto_teses)
            else:
                resultado_revisado = self._executar_agente_unico(nome_agente, revisao=instrucao_revisao)
            
            # Atualiza resultado
            self.resultados[nome_agente] = resultado_revisado
        
        return False  # Retorna False pois ainda há revisões pendentes
    
    def arquivo_final_valido(self) -> bool:
        ''' Verifica se os arquivos finais já existem e contêm dados válidos.
            
            Ambos os arquivos devem existir para considerar extração completa:
            1. <id_peca>.json - arquivo principal de extração
            2. <id_peca>.resumo.json - arquivo de resumo de tokens
            
            Casos válidos para o arquivo principal:
            1. Arquivo com pelo menos um campo preenchido (teses, jurisprudências, etc)
            2. Arquivo com metadados indicando que não havia campos para extrair (campos_identificados vazio)
            
            Returns:
                bool: True se ambos os arquivos existem e o principal é válido, False caso contrário
        '''
        # Verifica se o arquivo principal de extração existe
        if not self.arquivo_resultado or not os.path.exists(self.arquivo_resultado):
            return False
        
        # Verifica se o arquivo de resumo de tokens existe
        if not self.arquivo_resumo or not os.path.exists(self.arquivo_resumo):
            return False
        
        try:
            with open(self.arquivo_resultado, 'r', encoding='utf-8') as f:
                espelho_existente = json.load(f)
            
            # Verifica se tem metadados
            metadados = espelho_existente.get('metadados', {})
            if not isinstance(metadados, dict):
                return False
            
            # Caso 1: Verifica se nenhum campo foi identificado (caso válido sem dados)
            campos_identificados = metadados.get('campos_identificados', [])
            if isinstance(campos_identificados, list) and len(campos_identificados) == 0:
                # Arquivo considerado inválido: agente campos não identificou campos de extração?
                return False
            
            # Caso 2: Verifica se tem pelo menos uma chave com dados extraídos
            chaves_com_dados = [
                'teseJuridica', 'jurisprudenciaCitada', 'referenciasLegislativas',
                'notas', 'informacoesComplementares', 'termosAuxiliares', 'tema'
            ]
            
            for chave in chaves_com_dados:
                valor = espelho_existente.get(chave)
                if valor and len(valor) > 0:
                    return True
            
            # Arquivo existe mas não tem dados válidos nem campos_identificados vazio
            return False
            
        except Exception:
            return False
    
    def executar(self):
        ''' Executa a orquestração completa da extração do espelho.
            
            Pipeline de execução:
            1. AgenteCampos - identifica campos necessários
            2. AgenteTeses - extrai teses (dependência: nenhuma)
            3. AgenteJurisprudenciasCitadas - extrai jurisprudências com dependência das teses extraídas
            4. Agentes em paralelo:
               - AgenteNotas
               - AgenteInformacoesComplementares
               - AgenteTermosAuxiliares
               - AgenteTema
               - AgenteReferenciasLegislativas
            5. AgenteValidacaoFinal - valida e coordena revisões
            6. Loop de revisão conforme necessário
            
            Returns:
                dict: Espelho completo do acórdão com todos os campos extraídos
        '''
        inicio_orquestracao = datetime.now()
        
        if not self.texto_peca:
            raise ValueError("Texto do acórdão não fornecido")
        
        # Verifica se deve ignorar execução caso arquivo já exista e seja válido
        if self.ignorar_se_existir and self.arquivo_final_valido():
            try:
                with open(self.arquivo_resultado, 'r', encoding='utf-8') as f:
                    espelho_existente = json.load(f)
                
                self._registrar_log(f"Arquivo existente encontrado com dados: {self.arquivo_resultado}")
                self._registrar_log("Ignorando execução e retornando dados existentes")
                espelho_existente['carregado'] = True
                return espelho_existente
                
            except Exception as e:
                self._registrar_log(f"Erro ao carregar arquivo existente: {str(e)}", 'warning')
                self._registrar_log("Prosseguindo com a execução")

        if self.pasta_observabilidade:
            # limpa saídas anteriores para a peça
            self.limpar_observabilidade()
        
        self._registrar_log(f"=== Iniciando orquestração para peça {self.id_peca} ===")
        
        # Reseta resultados
        self.resultados = {}
        self._campos_para_extrair = set()
        
        # ===== ETAPA 1: Identificação de Campos =====
        self._registrar_log("ETAPA 1: Identificação de campos necessários")
        resposta_campos = self._executar_agente_unico('AgenteCampos')
        self.resultados['AgenteCampos'] = resposta_campos
        
        # Extrai quais campos precisam ser processados
        self._campos_para_extrair = self._extrair_campos_necessarios(resposta_campos)
        
        # ===== ETAPA 1.5: Revisão do AgenteCampos se não identificou campos =====
        if not self._campos_para_extrair and 'erro' not in resposta_campos:
            self._registrar_log("ETAPA 1.5: Nenhum campo identificado - solicitando revisão ao AgenteCampos", 'warning')
            # texto com os nomes dos campos para revisar
            txt_campso = ", ".join(MAPEAMENTO_TAGS_AGENTES.keys())
            revisao_campos = f"Por favor, confira atentamente se realmente não há campos para extrair no texto do acórdão. Os campos possíveis são: {txt_campso}. Se houver qualquer campo aplicável, extraia-os corretamente conforme instruções fornecidas."
            resposta_campos_revisada = self._executar_agente_unico('AgenteCampos', revisao=revisao_campos)
            self.resultados['AgenteCampos'] = resposta_campos_revisada
            
            # Reextrai campos após revisão
            self._campos_para_extrair = self._extrair_campos_necessarios(resposta_campos_revisada)
            
            if not self._campos_para_extrair:
                self._registrar_log("Após revisão, AgenteCampos confirmou que não há campos para extração", 'warning')
            else:
                self._registrar_log(f"Após revisão, AgenteCampos identificou campos: {', '.join(self._campos_para_extrair)}")
        
        # ===== ETAPA 2: Extração de Teses (obrigatória se identificada) =====
        if 'AgenteTeses' in self._campos_para_extrair:
            self._registrar_log("ETAPA 2: Extração de teses jurídicas")
            resposta_teses = self._executar_agente_unico('AgenteTeses')
            self.resultados['AgenteTeses'] = resposta_teses
        
        # ===== ETAPA 2.5: Extração de Jurisprudência Citada (depende de Teses) =====
        if 'AgenteJurisprudenciasCitadas' in self._campos_para_extrair:
            self._registrar_log("ETAPA 2.5: Extração de jurisprudência citada (com contexto de teses)")
            # Extrai apenas as teses extraídas (sem metadados de execução)
            contexto_teses = self.resultados.get('AgenteTeses', {}).get('resposta', {})
            resposta_juris = self._executar_agente_unico('AgenteJurisprudenciasCitadas', contexto_adicional=contexto_teses)
            self.resultados['AgenteJurisprudenciasCitadas'] = resposta_juris
        
        # ===== ETAPA 3: Extração em Paralelo dos Demais Campos =====
        self._registrar_log("ETAPA 3: Extração paralela dos demais campos")
        
        # Define agentes que podem rodar em paralelo (todos exceto Campos, Teses e JurisCitadas já executados)
        agentes_paralelo = [
            agente for agente in self._campos_para_extrair
            if agente not in ['AgenteCampos', 'AgenteTeses', 'AgenteJurisprudenciasCitadas']
        ]
        
        if agentes_paralelo:
            resultados_paralelo = self._executar_agentes_paralelo(agentes_paralelo)
            self.resultados.update(resultados_paralelo)
        
        # ===== ETAPA 4: Validação Final =====
        self._registrar_log("ETAPA 4: Validação final e consolidação")
        
        # Inicializa variáveis de loop de revisão
        loop_revisao = 0
        validacao_aprovada = False
        
        # Só executa validação se houver campos para extrair
        if self._campos_para_extrair:
            # Prepara saídas para o validador (somente nome e resposta, sem tokens/usage)
            # Identifica agentes que retornaram erro
            agentes_com_erro = []
            saidas_para_validacao = {}
            for agente, resultado in self.resultados.items():
                if agente not in ['AgenteCampos', 'AgenteValidacaoFinal']:  # AgenteCampos já foi revisado na etapa prévia
                    # Verifica se há erro na resposta
                    if 'erro' in resultado:
                        agentes_com_erro.append(agente)
                        self._registrar_log(f"AVISO: Agente {agente} retornou erro: {resultado.get('erro')}", 'warning')
                        # Inclui informação de erro para validação
                        saidas_para_validacao[agente] = {
                            'agente': agente,
                            'resposta': {
                                'erro': resultado.get('erro')
                            }
                        }
                    else:
                        # Extrai apenas a resposta (limpa de chaves desnecessárias)
                        resposta_limpa = self._limpar_resposta_para_validacao(resultado.get('resposta', {}))
                        saida_agente = {
                            'agente': agente,
                            'resposta': resposta_limpa
                        }
                        # Adiciona informação de revisão se houver
                        if agente in self._ultimas_revisoes:
                            saida_agente['revisao_solicitada'] = self._ultimas_revisoes[agente]
                        saidas_para_validacao[agente] = saida_agente
            
            # Se há agentes com erro, cria instruções de revisão para o validador processar
            if agentes_com_erro:
                self._registrar_log(f"Detectados {len(agentes_com_erro)} agentes com erro: {', '.join(agentes_com_erro)}")
            
            # Executa validação
            resposta_validacao = self._executar_agente_unico(
                'AgenteValidacaoFinal',
                contexto_adicional={
                    'saidas': saidas_para_validacao,
                    'campos_aprovados': list(self._campos_aprovados)
                }
            )
            self.resultados['AgenteValidacaoFinal'] = resposta_validacao
            
            # ===== ETAPA 5: Loop de Revisão =====
            max_loops_revisao = 2  # Máximo de ciclos de revisão
            
            while loop_revisao < max_loops_revisao and not validacao_aprovada:
                loop_revisao += 1
                self._registrar_log(f"LOOP DE REVISÃO {loop_revisao}/{max_loops_revisao}")
                
                # Verifica se há agentes com erro que precisam ser reexecutados
                agentes_com_erro_atual = []
                for agente, resultado in self.resultados.items():
                    if agente not in ['AgenteCampos', 'AgenteValidacaoFinal'] and 'erro' in resultado:
                        agentes_com_erro_atual.append(agente)
                
                # Se há erros, adiciona instruções de revisão automática para esses agentes
                if agentes_com_erro_atual:
                    self._registrar_log(f"Adicionando instruções de revisão para {len(agentes_com_erro_atual)} agentes com erro")
                    
                    # Extrai revisões do validador (se houver)
                    resposta_agente = resposta_validacao.get('resposta', {})
                    if isinstance(resposta_agente, dict):
                        revisao_validador = resposta_agente.get('revisao', {})
                    else:
                        revisao_validador = {}
                    
                    # Adiciona instruções simples para agentes com erro
                    for agente_erro in agentes_com_erro_atual:
                        if agente_erro not in revisao_validador:
                            revisao_validador[agente_erro] = "A extração anterior retornou erro. Por favor, tente novamente realizar a extração conforme as instruções do seu prompt base."
                            self._registrar_log(f"Adicionada instrução de revisão automática para {agente_erro}")
                    
                    # Cria resposta de validação modificada com as revisões
                    if revisao_validador:
                        resposta_validacao_modificada = {
                            'resposta': {
                                'revisao': revisao_validador,
                                'validacao_aprovada': False,
                                'contribuição': f"Revisão necessária para {len(revisao_validador)} agentes (incluindo {len(agentes_com_erro_atual)} com erro)"
                            }
                        }
                        resposta_validacao = resposta_validacao_modificada
                
                # Processa revisões e verifica se foi aprovada
                validacao_aprovada = self._processar_revisao(resposta_validacao)
                
                if validacao_aprovada:
                    self._registrar_log("Validação aprovada - encerrando loop de revisão")
                    break
                
                # Reexecuta validação com novos resultados (somente nome e resposta)
                saidas_para_validacao = {}
                agentes_com_erro = []
                for agente, resultado in self.resultados.items():
                    if agente not in ['AgenteCampos', 'AgenteValidacaoFinal']:
                        # Verifica novamente se há erro
                        if 'erro' in resultado:
                            agentes_com_erro.append(agente)
                            saidas_para_validacao[agente] = {
                                'agente': agente,
                                'resposta': {
                                    'erro': resultado.get('erro')
                                }
                            }
                        else:
                            resposta_limpa = self._limpar_resposta_para_validacao(resultado.get('resposta', {}))
                            saida_agente = {
                                'agente': agente,
                                'resposta': resposta_limpa
                            }
                            # Adiciona informação de revisão se houver
                            if agente in self._ultimas_revisoes:
                                saida_agente['revisao_solicitada'] = self._ultimas_revisoes[agente]
                            saidas_para_validacao[agente] = saida_agente
                
                if agentes_com_erro:
                    self._registrar_log(f"Após revisão, ainda há {len(agentes_com_erro)} agentes com erro: {', '.join(agentes_com_erro)}", 'warning')
                
                resposta_validacao = self._executar_agente_unico(
                    'AgenteValidacaoFinal',
                    contexto_adicional={
                        'saidas': saidas_para_validacao,
                        'campos_aprovados': list(self._campos_aprovados)
                    }
                )
                self.resultados['AgenteValidacaoFinal'] = resposta_validacao
            
            # Verifica se saiu do loop sem aprovação
            if not validacao_aprovada:
                self._registrar_log(f"Loop de revisão encerrado sem aprovação completa após {loop_revisao} iterações", 'warning')
        else:
            # Sem campos identificados - não há validação ou revisão
            self._registrar_log("Nenhum campo identificado - pulando validação e revisão")
        
        # ===== CONSOLIDAÇÃO FINAL - Construção Automática do Espelho =====
        duracao_total = (datetime.now() - inicio_orquestracao).total_seconds()
        self._registrar_log(f"=== Orquestração concluída em {duracao_total:.2f}s ===")
        
        # Extrai campos diretamente das respostas dos agentes (não mais do validador)
        def extrair_campo_resposta(agente_nome: str, campo_nome: str, default=None):
            """Extrai um campo da resposta de um agente de forma robusta
            
            Após a correção em get_resposta, a estrutura é:
            resultado[agente_nome] = {
                'resposta': {...},  # já é dict, não mais string
                'usage': {...}
            }
            """
            if agente_nome not in self.resultados:
                self._registrar_log(f"DEBUG extrair_campo: agente '{agente_nome}' não encontrado em resultados", 'warning')
                return default if default is not None else []
            
            resultado = self.resultados[agente_nome]
            if not isinstance(resultado, dict):
                self._registrar_log(f"DEBUG extrair_campo: resultado de '{agente_nome}' não é dict: {type(resultado)}", 'warning')
                return default if default is not None else []
            
            # Acessa campo 'resposta' que já vem como dict
            resposta = resultado.get('resposta', {})
            
            # resposta já deve ser dict (não é mais string JSON)
            if not isinstance(resposta, dict):
                self._registrar_log(f"DEBUG extrair_campo: 'resposta' de '{agente_nome}' não é dict: {type(resposta)}", 'warning')
                return default if default is not None else []
            
            # Tenta pegar o campo específico
            if campo_nome in resposta:
                valor = resposta[campo_nome]
                self._registrar_log(f"DEBUG extrair_campo: '{campo_nome}' encontrado em '{agente_nome}', tipo: {type(valor)}, len: {len(valor) if isinstance(valor, (list, dict, str)) else 'N/A'}")
                return valor
            else:
                self._registrar_log(f"DEBUG extrair_campo: campo '{campo_nome}' NÃO encontrado em '{agente_nome}'. Chaves disponíveis: {list(resposta.keys())}", 'warning')
            
            self._registrar_log(f"DEBUG extrair_campo: campo '{campo_nome}' não encontrado em '{agente_nome}'", 'warning')
            return default if default is not None else []
        
        # Monta espelho final extraindo campos de cada agente
        espelho_final = {
            'id_peca': self.id_peca,
            'teseJuridica': extrair_campo_resposta('AgenteTeses', 'teseJuridica', []),
            'jurisprudenciaCitada': extrair_campo_resposta('AgenteJurisprudenciasCitadas', 'jurisprudenciaCitada', []),
            'referenciasLegislativas': extrair_campo_resposta('AgenteReferenciasLegislativas', 'referenciasLegislativas', []),
            'notas': extrair_campo_resposta('AgenteNotas', 'notas', []),
            'informacoesComplementares': extrair_campo_resposta('AgenteInformacoesComplementares', 'informacoesComplementares', []),
            'termosAuxiliares': extrair_campo_resposta('AgenteTermosAuxiliares', 'termosAuxiliares', []),
            'tema': extrair_campo_resposta('AgenteTema', 'tema', []),
            'metadados': {
                'campos_identificados': list(self._campos_para_extrair),
                'loops_revisao': loop_revisao,
                'validacao_aprovada': validacao_aprovada,
                'duracao_total_segundos': duracao_total,
                'timestamp_extracao': inicio_orquestracao.isoformat()
            }
        }
        
        # Não adiciona mais a chave 'resultado' - 02_agentes_gerar_espelhos.py verifica campos_identificados vazio
        
        # Log de debug do espelho final
        self._registrar_log(f"DEBUG espelho_final construído com {sum(1 for k, v in espelho_final.items() if k != 'metadados' and v and len(v) > 0)} campos não-vazios")
        
        # Adiciona observabilidade ao resultado
        dados_observabilidade = {
            'duracao_total_segundos': duracao_total,
            'loops_revisao': loop_revisao,
            'campos_extraidos': list(self._campos_para_extrair),
            'total_agentes_executados': len(self.resultados)
        }
        self._soma_observabilidade('OrquestracaoFinal', dados_observabilidade)
        
        # Verifica se há erros que impedem a gravação
        # Só grava arquivo se NÃO houver erros em NENHUM agente
        # Casos válidos:
        # 1. Execução com campos identificados e extraídos com sucesso
        # 2. Execução sem campos identificados (AgenteCampos não encontrou campos - não é erro)
        # Nota: Não identificar campos é diferente de ter erro - verificar presença da chave 'erro'
        tem_erros = any('erro' in resultado for agente, resultado in self.resultados.items())
        
        if not tem_erros:
            # Grava arquivos de saída se pasta estiver definida
            self._gravar_resultado_final(espelho_final)
            self._gravar_resumo_observabilidade_md()
            self._gravar_resumo_tokens()
        else:
            self._registrar_log("Arquivos não gravados devido a erros na extração", 'warning')
        
        return espelho_final
    
    def _gravar_resultado_final(self, espelho_final: dict):
        ''' Grava o resultado final da extração em arquivo JSON de forma thread-safe.
        '''
        if not self.arquivo_resultado:
            return
        
        try:
            with self._lock_arquivo:
                # Grava arquivo com identação
                with open(self.arquivo_resultado, 'w', encoding='utf-8') as f:
                    json.dump(espelho_final, f, ensure_ascii=False, indent=2)
                
                self._registrar_log(f"Resultado final gravado em: {self.arquivo_resultado}")
        except Exception as e:
            self._registrar_log(f"Erro ao gravar resultado final: {str(e)}", 'error')
    
    def _gravar_resumo_observabilidade_md(self):
        ''' Grava o resumo de observabilidade em formato Markdown de forma thread-safe.
        '''
        if not self.pasta_observabilidade or not self.id_peca:
            return
        
        try:
            with self._lock_arquivo:
                arquivo_md = os.path.join(self.pasta_observabilidade, f'{self.id_peca}.obs.md')
                
                # Gera o resumo textual
                resumo_texto = self.resumo_observabilidade()
                
                # Grava arquivo markdown
                with open(arquivo_md, 'w', encoding='utf-8') as f:
                    f.write(resumo_texto)
                
                self._registrar_log(f"Resumo de observabilidade gravado em: {arquivo_md}")
        except Exception as e:
            self._registrar_log(f"Erro ao gravar resumo de observabilidade: {str(e)}", 'error')
    
    def _extrair_tokens_por_campo(self) -> dict:
        ''' Extrai estatísticas de tokens por campo/agente a partir da observabilidade.
        '''
        resumo_tokens = {
            'id_peca': self.id_peca,
            'total_geral': {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'cached_tokens': 0,
                'reasoning_tokens': 0,
                'total_tokens': 0,
                'time': 0.0
            },
            'por_agente': {}
        }
        
        # Processa cada agente
        for agente, execucoes in self.observabilidade.items():
            if agente == 'OrquestracaoFinal':
                continue
            
            tokens_agente = {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'cached_tokens': 0,
                'reasoning_tokens': 0,
                'total_tokens': 0,
                'execucoes': len(execucoes),
                'time': 0.0
            }
            
            # Soma tokens e tempo de todas as execuções do agente
            for exec_info in execucoes:
                resposta = exec_info.get('resposta', {})
                
                # Busca dados de usage na resposta
                if isinstance(resposta, dict):
                    usage = resposta.get('usage', {})
                    if isinstance(usage, dict):
                        tokens_agente['prompt_tokens'] += usage.get('prompt_tokens', 0)
                        tokens_agente['completion_tokens'] += usage.get('completion_tokens', 0)
                        tokens_agente['cached_tokens'] += usage.get('cached_tokens', 0)
                        tokens_agente['reasoning_tokens'] += usage.get('reasoning_tokens', 0)
                        tokens_agente['total_tokens'] += usage.get('total_tokens', 0)
                
                # Soma tempo de execução
                duracao = exec_info.get('duracao_segundos', 0)
                tokens_agente['time'] += duracao
            
            # Adiciona ao resumo
            if tokens_agente['total_tokens'] > 0:
                resumo_tokens['por_agente'][agente] = tokens_agente
                
                # Acumula no total geral
                resumo_tokens['total_geral']['prompt_tokens'] += tokens_agente['prompt_tokens']
                resumo_tokens['total_geral']['completion_tokens'] += tokens_agente['completion_tokens']
                resumo_tokens['total_geral']['cached_tokens'] += tokens_agente['cached_tokens']
                resumo_tokens['total_geral']['reasoning_tokens'] += tokens_agente['reasoning_tokens']
                resumo_tokens['total_geral']['total_tokens'] += tokens_agente['total_tokens']
                resumo_tokens['total_geral']['time'] += tokens_agente['time']
        
        return resumo_tokens
    
    def _gravar_resumo_tokens(self):
        ''' Grava o resumo de tokens em formato JSON de forma thread-safe.
        '''
        if not self.arquivo_resumo:
            return
        
        try:
            with self._lock_arquivo:
                # Extrai estatísticas de tokens
                resumo_tokens = self._extrair_tokens_por_campo()
                
                # ✨ CORREÇÃO: Ajusta tempos para usar tempo real vs tempo linear (somado)
                if 'OrquestracaoFinal' in self.observabilidade:
                    tempo_real = self.observabilidade['OrquestracaoFinal'][0].get('duracao_total_segundos', 0)
                    if tempo_real > 0:
                        # Preserva tempo somado em campo separado (time_linear)
                        tempo_linear = resumo_tokens['total_geral']['time']
                        resumo_tokens['total_geral']['time_linear'] = tempo_linear
                        # Sobrescreve 'time' com tempo real da orquestração
                        resumo_tokens['total_geral']['time'] = tempo_real
                        
                        self._registrar_log(f"Tempo ajustado: linear={tempo_linear:.2f}s -> real={tempo_real:.2f}s")
                
                # Grava arquivo com identação
                with open(self.arquivo_resumo, 'w', encoding='utf-8') as f:
                    json.dump(resumo_tokens, f, ensure_ascii=False, indent=2)
                
                self._registrar_log(f"Resumo de tokens gravado em: {self.arquivo_resumo}")
        except Exception as e:
            self._registrar_log(f"Erro ao gravar resumo de tokens: {str(e)}", 'error')
    
    def resumo_observabilidade(self) -> str:
        ''' Gera um relatório textual resumido dos dados de observabilidade.
        '''
        linhas = []
        linhas.append("=" * 80)
        linhas.append("RELATÓRIO DE OBSERVABILIDADE - EXTRAÇÃO DE ESPELHO")
        linhas.append("=" * 80)
        linhas.append("")
        
        # Resumo geral
        if 'OrquestracaoFinal' in self.observabilidade:
            dados_finais = self.observabilidade['OrquestracaoFinal'][0]
            linhas.append("RESUMO GERAL:")
            linhas.append(f"  Duração Total: {dados_finais.get('duracao_total_segundos', 0):.2f}s")
            linhas.append(f"  Loops de Revisão: {dados_finais.get('loops_revisao', 0)}")
            linhas.append(f"  Campos Extraídos: {', '.join(dados_finais.get('campos_extraidos', []))}")
            linhas.append(f"  Total de Agentes: {dados_finais.get('total_agentes_executados', 0)}")
            linhas.append("")
        
        # Detalhes por agente
        linhas.append("DETALHES POR AGENTE:")
        linhas.append("")
        
        for agente, execucoes in self.observabilidade.items():
            if agente == 'OrquestracaoFinal':
                continue
            
            linhas.append(f"  {agente}:")
            for i, exec_info in enumerate(execucoes, 1):
                linhas.append(f"    Execução {i}:")
                linhas.append(f"      Duração: {exec_info.get('duracao_segundos', 0):.2f}s")
                linhas.append(f"      Iterações: {exec_info.get('iteracoes', 0)}")
                linhas.append(f"      Sucesso: {'Sim' if exec_info.get('sucesso', False) else 'Não'}")
                if 'erro' in exec_info:
                    linhas.append(f"      Erro: {exec_info['erro']}")
                if exec_info.get('tem_revisao'):
                    linhas.append(f"      Revisão: Sim")
            linhas.append("")
        
        # Log de eventos
        if self.log:
            linhas.append("LOG DE EVENTOS:")
            linhas.append("")
            for entrada in self.log:
                timestamp = entrada.get('timestamp', '')
                nivel = entrada.get('nivel', 'info').upper()
                mensagem = entrada.get('mensagem', '')
                linhas.append(f"  [{timestamp}] {nivel}: {mensagem}")
            linhas.append("")
        
        linhas.append("=" * 80)
        
        return "\n".join(linhas)
    
    def resetar(self):
        ''' Reseta o estado do orquestrador para nova execução.
            Nota: Este método não é mais necessário pois cada instância processa apenas uma peça.
            Mantido para compatibilidade com código existente.
        '''
        self.resultados = {}
        self._campos_para_extrair = set()
        self.observabilidade = {}
        self.log = []
        self._agentes_instancias = {}
        
    def limpar_observabilidade(self):
        ''' Limpa arquivos de observabilidade anteriores para a peça atual.
        '''
        if not self.pasta_observabilidade or not self.id_peca:
            return
        
        try:
            with self._lock_arquivo:
                padrao_arquivos = os.path.join(self.pasta_observabilidade, f'{self.id_peca}.*')
                arquivos_existentes = glob(padrao_arquivos)
                
                for arquivo in arquivos_existentes:
                    extensao = os.path.splitext(arquivo)[1].lower()
                    if extensao in ['.txt', '.json', '.md']:
                        os.remove(arquivo)
                        self._registrar_log(f"Arquivo de observabilidade removido: {arquivo}")
        except Exception as e:
            self._registrar_log(f"Erro ao limpar observabilidade: {str(e)}", 'warning')
            
    def get_mensagens_erro(self, espelho: dict) -> dict:
        ''' Extrai mensagens de erro dos resultados dos agentes no espelho.
            
            Returns:
                dict: Dicionário com nomes dos agentes como chaves e mensagens de erro como valores
        '''
        mensagens_erro = {}
        erros = []
        for agente, resultado in self.resultados.items():
            if 'erro' in resultado:
                mensagens_erro[agente] = resultado['erro']
                erros.append(f"{agente}: {resultado['erro']}")
        if any(erros):
            mensagens_erro['erros'] = '\n'.join(erros)
        return mensagens_erro