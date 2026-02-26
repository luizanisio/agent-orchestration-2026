# -*- coding: utf-8 -*-
"""
Autor: Luiz Anísio
Fonte: https://github.com/luizanisio/llms/tree/main/experimentos/agentes-esp-acordao
Data: 14/11/2025

Descrição:
-----------
Centraliza as chamadas dos agentes, llms-as-a-judge e outros prompts, simplificando 
a mudança para outras APIs ou ajustes de acordo com as necessidades do projeto. 
"""

import sys
sys.path.append('../src')

from util import UtilEnv
if not UtilEnv.carregar_env('.env', pastas=['./','../', '../src']):
    raise EnvironmentError('Não foi possível carregar o arquivo .env')

from util_openai import get_resposta
# cria um método simplificado de chamada do prompt usando util_openai.get_resposta 
# pode ser adaptado de acordo com a api que for utilizada para as extrações
def send_prompt(*args, **kwargs):
    if not UtilEnv.get_str('PESSOAL_OPENROUTER_API_KEY'):
        raise EnvironmentError('⚠️ Não foi possível carregar a sua API-KEY do OpenRouter em PESSOAL_OPENROUTER_API_KEY no arquivo .env!')
    if 'sg_modelo' in kwargs:
        kwargs['modelo'] = kwargs.pop('sg_modelo','')
    if 'prompt_retorna_json' in kwargs:
        kwargs['as_json'] = kwargs.pop('prompt_retorna_json')
    kwargs['silencioso'] = True
    res = get_resposta(*args, **kwargs)
    res['tratada'] = True
    return res

def teste_open_router():
    from util_openai import get_resposta
    prompt = 'Responda 2 + 2 = ? no formato json: {"resposta": valor}'
    # modelos gratuitos nem sempre estão disponíveis
    # verificar no site https://openrouter.ai/models quais estão disponíveis no momento
    # colocar od: para o get_resposta(..) identificar que é o openroter
    #modelo = 'or:google/gemma-3-3b-it:floor'
    #modelo = 'or:google/gemini-2.0-flash-exp:free'
    modelo = 'or:google/gemma-3-27b-it:floor'
    #modelo = 'or:nvidia/nemotron-3-nano-30b-a3b:free'
    #modelo = 'or:openai/gpt-5'
    #modelo = 'gpt-5' # api openai
    resposta = get_resposta(prompt, papel = 'responser rápido',
                            modelo=modelo, 
                            max_tokens=500,
                            think='medium:low',
                            as_json=True, silencioso=False)
    if not isinstance(resposta, dict):
        print('Resposta do modelo não está em formato JSON:', resposta)
        exit(1)
    if ('error' in resposta):
        print('Erro retornado pelo modelo:', resposta)
        exit(1)
    if not resposta.get('resposta'):
        print('Resposta do modelo não contém o campo "resposta":', resposta)
        exit(1)
    print('Resposta do modelo:', resposta.get('resposta'))

if __name__ == "__main__":
    teste_open_router()