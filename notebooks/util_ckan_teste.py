''' Teste unitário da classe UtilCkan.
    Contém diversos cenários de filtros no construtor e suas respectivas
    expectativas de saída após o cruzamento de dados de espelhos e íntegras.
'''

import unittest
from util_ckan import UtilCkan

class TestUtilCkanFiltros(unittest.TestCase):
    """Testes baseados em dicionários de entrada/saída para facilitar a manutenção."""
    
    def test_filtros_diversos(self):
        # Lista de dicionários descrevendo os cenários de teste.
        # parâmetros: argumentos passados para inicializar UtilCkan.
        # esperados : chaves/valores esperados no cruzamento ou no mapa de íntegras correspondente.
        cenarios = [
            {
                'nome': 'Filtro completo por tupla de 3 (registro, data, tipo) e seq_documento',
                'parametros': {
                    'orgaos': ['T2'],
                    'registros': [('202302829818', '20240822', 'ACÓRDÃO')],
                    'documentos': [266239985],
                },
                'esperados': {
                    'id_mapa': '202302829818.20240822.ACÓRDÃO',
                    'orgao': 'T2',
                    'ministro': 'HERMAN BENJAMIN',
                    'tem_integra': True
                }
            },
            {
                'nome': 'Filtro por tupla de 2 (registro, data) - formato com hífen',
                'parametros': {
                    'registros': [('202302829818', '2024-08-22')],
                },
                'esperados': {
                    'id_mapa': '202302829818.20240822.ACÓRDÃO',
                    'orgao': 'T2',
                    'tem_integra': True
                }
            },
            {
                'nome': 'Filtro simplificado apenas pela string do número do registro',
                'parametros': {
                    'registros': ['202302829818'],
                },
                'esperados': {
                    'id_mapa': '202302829818.20240822.ACÓRDÃO',
                    'numero_registro': '202302829818',
                    'tem_integra': True
                }
            },
            {
                'nome': 'Filtro simplificado exclusivo por seq_documento',
                'parametros': {
                    'documentos': [266239985],
                },
                'esperados': {
                    'id_mapa': '202302829818.20240822.ACÓRDÃO',
                    'tem_integra': True
                }
            },
            {
                'nome': 'Filtro por múltiplos registros de datasets distintos com formatos de data variados',
                'parametros': {
                    'registros': [
                        ('202201876389', 1656644400000), 
                        ('202400109342', '2025-11-12')
                    ],
                },
                'esperados': {
                    'id_mapa_multiplos': [
                        '202201876389.20220701.ACÓRDÃO',
                        '202400109342.20251112.ACÓRDÃO'
                    ]
                }
            },
        ]
        
        for cenario in cenarios:
            with self.subTest(cenario=cenario['nome']):
                # Ao passar True em atualizar_cache_e_mapas, garantimos que 
                # a classe utilizará a restrição imediata no mapeamento via json em disco.
                ckan = UtilCkan(**cenario['parametros'], atualizar_cache_e_mapas=True)
                
                # Executa o cruzamento limpo
                resultado = ckan.cruzar_espelhos_integras()
                
                # Validamos que pelo menos 1 registro corresponde ao filtro
                self.assertGreater(len(resultado), 0, f"Falhou no {cenario['nome']}: não retornou resultados.")
                
                esperado = cenario['esperados']

                # Tratamento para validação de múltiplos id_mapa simultâneos
                if 'id_mapa_multiplos' in esperado:
                    ids_retornados = [r.get('id_mapa') for r in resultado]
                    for id_esperado in esperado['id_mapa_multiplos']:
                        self.assertIn(id_esperado, ids_retornados, f"ID {id_esperado} não retornado na busca de múltiplos itens.")
                else:    
                    # Pega a primeira ocorrência do cruzamento para testes de item único
                    res_dict = resultado[0]
                    
                    # Checagens comuns resultantes
                    if 'id_mapa' in esperado:
                        self.assertEqual(res_dict.get('id_mapa'), esperado['id_mapa'])
                    if 'orgao' in esperado:
                        self.assertEqual(res_dict.get('orgao'), esperado['orgao'])
                    if 'numero_registro' in esperado:
                        self.assertEqual(res_dict.get('numero_registro'), esperado['numero_registro'])
                    if 'tem_integra' in esperado:
                        self.assertEqual(res_dict.get('tem_integra'), esperado['tem_integra'])
                        
                    # Alguns dados da íntegra em específico estão no mapa secundário
                    if 'ministro' in esperado:
                        id_mapa = esperado['id_mapa']
                        integra_dict = ckan._mapa_integras.get(id_mapa, {})
                        self.assertEqual(integra_dict.get('ministro'), esperado['ministro'])

if __name__ == '__main__':
    unittest.main()
