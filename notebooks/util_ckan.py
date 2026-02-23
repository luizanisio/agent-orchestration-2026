# -*- coding: utf-8 -*-
"""
Autor: Luiz Anísio
Fonte: https://github.com/luizanisio/agent-orchestration-2026

Descrição:
-----------
Utilitários CKAN para os notebooks do projeto JAMEX.
Centraliza listagem de recursos, download com cache, processamento de ZIPs
e leitura de JSONs de espelhos de acórdãos do STJ.

Arquitetura de Mapas:
---------------------
A classe mantém dois arquivos de índice (JSON) que mapeiam **todos** os
documentos publicados no Portal de Dados Abertos do STJ:

    mapa_espelhos.json  — índice dos JSONs de espelhos
    mapa_integras.json  — índice dos metadados dentro dos ZIPs de íntegras

Cada registro contém a chave composta:
    id_mapa = {numeroRegistro}.{YYYYMMDD}.{tipoDecisao}

Essa chave liga espelhos às íntegras de forma unívoca.
Quando há duplicatas para um mesmo id_mapa, elas são registradas em
self.duplicados (dict) para análise posterior, sem interromper o processamento.

Como usar:
-----------
    from util_ckan import UtilCkan

    ckan = UtilCkan(
        anos   = {'2023', '2024'},
        orgaos = ['T5', 'T6', 'S3'],
    )

    # Atualiza os mapas (apenas novos arquivos são processados)
    ckan.atualizar_mapas()

    # Gera parquet com espelhos + íntegras
    df = ckan.gerar_dataset_espelhos('../data/exemplo.parquet', incluir_integras=True)

Parâmetros do construtor:
--------------------------
    anos                      : set[str] | None  — anos de publicação (YYYY). None = todos.
    classes                   : set[str] | None  — siglas de classes processuais. None = todas.
    registros                 : set[str] | None  — filtrar por numeroRegistro específico.
                                podem ser tuplas (registro, data_publicacao) ou (registro, data_publicacao, tipo_decisao)
    documentos                : set[int] | None  — filtrar por seq_documento_acordao específico.
    colunas                   : list[str] | None — campos do espelho a importar. None = padrão.
    orgaos                    : list[str] | None — siglas dos órgãos (ex: ['T5', 'S3']). None = todos.
    download_dir              : Path  — pasta raiz para cache (padrão: downloads_stj).
                                As subpastas espelhos/, integras/ e metadados_integras/ são criadas automaticamente.
    timeout                   : int   — timeout HTTP em segundos (padrão: 600).
    permitir_download_espelho : bool  — False = usa apenas cache para espelhos.
    permitir_download_integra : bool  — False = usa apenas cache para ZIPs de íntegras.
"""

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# ─── Constantes de datasets ──────────────────────────────────────────────────

DATASETS_ESPELHOS_PADRAO = [
    ('CE', 'espelhos-de-acordaos-corte-especial'),
    ('S1', 'espelhos-de-acordaos-primeira-secao'),
    ('S2', 'espelhos-de-acordaos-segunda-secao'),
    ('S3', 'espelhos-de-acordaos-terceira-secao'),
    ('T1', 'espelhos-de-acordaos-primeira-turma'),
    ('T2', 'espelhos-de-acordaos-segunda-turma'),
    ('T3', 'espelhos-de-acordaos-terceira-turma'),
    ('T4', 'espelhos-de-acordaos-quarta-turma'),
    ('T5', 'espelhos-de-acordaos-quinta-turma'),
    ('T6', 'espelhos-de-acordaos-sexta-turma'),
]

DATASET_TEXTOS_PADRAO = 'integras-de-decisoes-terminativas-e-acordaos-do-diario-da-justica'

COLUNAS_ESPELHO_PADRAO = [
    'id', 'numeroRegistro', 'siglaClasse', 'descricaoClasse',
    'nomeOrgaoJulgador', 'ministroRelator', 'tipoDeDecisao',
    'dataPublicacao', 'dataDecisao',
    'teseJuridica', 'tema', 'referenciasLegislativas',
    'jurisprudenciaCitada', 'notas', 'termosAuxiliares',
    'informacoesComplementares', 'acordaosSimilares',
]

CKAN_BASE_URL = 'https://dadosabertos.web.stj.jus.br'


# ─── Funções utilitárias de datas ─────────────────────────────────────────────

def _extrair_data_pub_espelho(valor: str) -> str:
    """Extrai YYYYMMDD de string tipo 'DJE        DATA:01/06/2023'."""
    if not valor:
        return ''
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', valor)
    return f'{m.group(3)}{m.group(2)}{m.group(1)}' if m else ''



def _padronizar_data_filtro(valor: str) -> str:
    """Padroniza data contida nos filtros (registros) para formato YYYYMMDD."""
    if not valor: return ''
    v = str(valor).strip()
    if re.match(r'^\d{8}$', v): return v
    
    # DD/MM/YYYY ou DD-MM-YYYY
    m = re.match(r'^(\d{2})[-/](\d{2})[-/](\d{4})$', v)
    if m: return f"{m.group(3)}{m.group(2)}{m.group(1)}"
    
    # YYYY-MM-DD ou YYYY/MM/DD
    m = re.match(r'^(\d{4})[-/](\d{2})[-/](\d{2})$', v)
    if m: return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    
    d = _extrair_data_pub_integra(v)
    if d: return d
    d = _extrair_data_pub_espelho(v)
    return d or v

def _extrair_data_pub_integra(valor) -> str:
    """Converte dataPublicacao de metadados de íntegra para YYYYMMDD.

    Aceita:
      - epoch-ms (int): 1685588400000 → 20230601
      - ISO string: '2024-02-08' → 20240208
    """
    if not valor:
        return ''
    # Tenta como string ISO (YYYY-MM-DD)
    if isinstance(valor, str):
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', valor)
        if m:
            return f'{m.group(1)}{m.group(2)}{m.group(3)}'
    # Tenta como epoch-ms
    try:
        ts = int(valor) / 1000
        return datetime.fromtimestamp(ts).strftime('%Y%m%d')
    except (ValueError, TypeError, OSError):
        return ''


def _gerar_id_mapa(num_registro: str, data_pub_yyyymmdd: str, tipo_decisao: str) -> str:
    """Gera a chave composta que liga espelhos a íntegras."""
    return f'{num_registro}.{data_pub_yyyymmdd}.{tipo_decisao.upper().strip()}'


class UtilCkan:
    """Acesso ao Portal de Dados Abertos do STJ via API CKAN.

    Filtros configurados no construtor são aplicados automaticamente
    nos métodos de alto nível.
    """

    def __init__(
        self,
        anos:    Optional[set[str]]    = None,
        classes: Optional[set[str]]    = None,
        orgaos:  Optional[list[str]]    = None,
        registros: Optional[set] = None,
        documentos: Optional[set] = None,
        colunas: Optional[list[str]] = None,
        download_dir: Path              = Path('downloads_stj'),
        base_url:     str               = CKAN_BASE_URL,
        timeout:      int               = 600,
        atualizar_cache_e_mapas: bool   = True,
    ):
        ''' Inicializa o utilitário CKAN.
        Args:
            anos: Anos de interesse (ex: {'2023', '2024'}).
            classes: Classes de processos (ex: {'AI', 'RE'}).
            orgaos: Siglas dos órgãos (ex: ['T1', 'T2']).
            registros: Números de registro (ex: {'123456'}).
            documentos: Sequências de documentos (ex: {123456}).
            colunas: Colunas a serem extraídas dos espelhos.
            download_dir: Diretório raiz para cache. Subpastas espelhos/, integras/ e
                metadados_integras/ são criadas automaticamente dentro dele.
            base_url: URL base do CKAN.
            timeout: Timeout HTTP em segundos.
            atualizar_cache_e_mapas: Permitir baixar novos arquivos via API CKAN e atualizar/recriar os mapas.
                - se False, usa apenas os arquivos e mapas já armazenados em cache.
                - será considerado True independentemente do valor fornecido se os mapas não forem encontrados na inicialização.
        '''

        self.anos         = set(anos) if anos else None
        self.classes      = {c.upper() for c in classes} if classes else None
        
        # Filtros de registros aceitam string ou tuplas (reg, data) ou (reg, data, tipo)
        self.registros = set()
        if registros:
            for r in registros:
                if isinstance(r, str):
                    self.registros.add(r.strip())
                elif isinstance(r, (tuple, list)):
                    if len(r) == 2:
                        self.registros.add((str(r[0]).strip(), _padronizar_data_filtro(r[1])))
                    elif len(r) >= 3:
                        self.registros.add((str(r[0]).strip(), _padronizar_data_filtro(r[1]), str(r[2]).upper().strip()))

        self.documentos = {str(d).strip() for d in documentos} if documentos else None
        self.colunas    = colunas or COLUNAS_ESPELHO_PADRAO

        # Filtra DATASETS_ESPELHOS_PADRAO pelas siglas informadas
        if orgaos:
            siglas = {s.upper() for s in orgaos}
            self.orgaos = [(s, d) for s, d in DATASETS_ESPELHOS_PADRAO if s in siglas]
            nao_encontrados = siglas - {s for s, _ in self.orgaos}
            if nao_encontrados:
                print(f'  ⚠️  Órgãos não reconhecidos: {nao_encontrados}')
        else:
            self.orgaos = DATASETS_ESPELHOS_PADRAO
        self.download_dir  = Path(download_dir)
        self.espelhos_dir  = self.download_dir / 'espelhos'
        self.metadados_dir = self.download_dir / 'metadados_integras'
        self.integras_dir  = self.download_dir / 'integras'
        self.base_url     = base_url
        self.timeout      = timeout
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.espelhos_dir.mkdir(parents=True, exist_ok=True)
        self.metadados_dir.mkdir(parents=True, exist_ok=True)
        self.integras_dir.mkdir(parents=True, exist_ok=True)

        # ── Mapas de índice ──
        self._caminho_mapa_espelhos = self.download_dir / 'mapa_espelhos.json'
        self._caminho_mapa_integras = self.download_dir / 'mapa_integras.json'
        self._mapa_espelhos: dict[str, dict] = {}   # id_mapa → registro
        self._mapa_integras: dict[str, dict] = {}   # id_mapa → registro
        self.duplicados: dict[str, list[dict]] = {}  # id_mapa → lista de ocorrências

        # Determina a necessidade de atualização forçada
        self.atualizar_cache_e_mapas = atualizar_cache_e_mapas
        if not self._caminho_mapa_espelhos.is_file() or not self._caminho_mapa_integras.is_file():
            self.atualizar_cache_e_mapas = True

        # Carrega mapas existentes do disco
        self._carregar_mapas()

        if self.atualizar_cache_e_mapas:
           self.baixar_espelhos()
           self.atualizar_mapas()

    def _passou_filtro_registro(self, num_reg: str, data_pub: str, tipo_decisao: str) -> bool:
        """Verifica se o registro satisfaz os filtros de tuplas de registros."""
        if not self.registros:
            return True
        num = num_reg.strip()
        data = data_pub.strip()
        tipo = tipo_decisao.upper().strip()
        return (
            (num in self.registros) or 
            ((num, data) in self.registros) or 
            ((num, data, tipo) in self.registros)
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Mapa — construção e consulta
    # ══════════════════════════════════════════════════════════════════════════

    def _carregar_mapas(self):
        """Carrega mapas do disco, se existirem."""
        if self._caminho_mapa_espelhos.is_file():
            dados = json.loads(self._caminho_mapa_espelhos.read_text('utf-8'))
            self._mapa_espelhos = dados.get('mapa', {})
            # restaura duplicados salvos previamente
            for dup in dados.get('duplicados', []):
                self.duplicados.setdefault(dup['id_mapa'], []).append(dup)
            print(f'  📋  Mapa espelhos carregado: {len(self._mapa_espelhos)} registros')
        if self._caminho_mapa_integras.is_file():
            dados = json.loads(self._caminho_mapa_integras.read_text('utf-8'))
            self._mapa_integras = dados.get('mapa', {})
            for dup in dados.get('duplicados', []):
                self.duplicados.setdefault(dup['id_mapa'], []).append(dup)
            print(f'  📋  Mapa íntegras carregado: {len(self._mapa_integras)} registros')

    def _salvar_mapa_espelhos(self):
        """Persiste mapa de espelhos no disco."""
        dups = [d for lst in self.duplicados.values() for d in lst if d.get('origem') == 'espelho']
        payload = {
            'atualizado_em': datetime.now().isoformat(),
            'total': len(self._mapa_espelhos),
            'duplicados': dups,
            'mapa': self._mapa_espelhos,
        }
        self._caminho_mapa_espelhos.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8'
        )

    def _salvar_mapa_integras(self):
        """Persiste mapa de íntegras no disco."""
        dups = [d for lst in self.duplicados.values() for d in lst if d.get('origem') == 'integra']
        payload = {
            'atualizado_em': datetime.now().isoformat(),
            'total': len(self._mapa_integras),
            'duplicados': dups,
            'mapa': self._mapa_integras,
        }
        self._caminho_mapa_integras.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8'
        )

    def _registrar_duplicado(self, id_mapa: str, registro_novo: dict, registro_existente: dict, origem: str):
        """Registra uma duplicata detectada durante a indexação."""
        entrada = {
            'id_mapa': id_mapa,
            'origem': origem,
            'existente': registro_existente,
            'duplicado': registro_novo,
        }
        self.duplicados.setdefault(id_mapa, []).append(entrada)

    def obter_duplicados(self, filtro=None) -> dict[str, list[dict]]:
        """Retorna dicionário com os id_mapa que possuem duplicatas e suas ocorrências.

        Args:
            filtro: Opcional. Restringe o resultado aos id_mapa presentes no conjunto
                    informado. Aceita:
                      - set / list  de strings  (id_mapa)
                      - pandas DataFrame com coluna 'id_mapa'
                    Se None, retorna todos os duplicados.
        """
        if filtro is None:
            return self.duplicados
        import pandas as pd
        if isinstance(filtro, pd.DataFrame):
            ids = set(filtro['id_mapa'].dropna()) if 'id_mapa' in filtro.columns else set()
        else:
            ids = set(filtro)
        return {k: v for k, v in self.duplicados.items() if k in ids}

    # ── Construção dos mapas ──────────────────────────────────────────────────

    def atualizar_mapas(self, forcar: bool = False):
        """Atualiza os dois mapas (espelhos + íntegras).

        Por padrão, processa apenas arquivos que ainda não foram indexados.
        Se `forcar=True`, reconstrói ambos os mapas do zero.
        """
        if forcar:
            self._mapa_espelhos = {}
            self._mapa_integras = {}
            self.duplicados = {}
        self._atualizar_mapa_espelhos()
        self._atualizar_mapa_integras()
        n_dups = sum(len(v) for v in self.duplicados.values())
        if n_dups:
            print(f'  ⚠️  {n_dups} duplicata(s) detectada(s) em {len(self.duplicados)} id_mapa(s). '
                  f'Use ckan.obter_duplicados() para analisar.')

    def _atualizar_mapa_espelhos(self):
        """Indexa todos os JSONs de espelhos em cache."""
        from tqdm.auto import tqdm

        # Arquivos já indexados
        arquivos_indexados = {
            v.get('arquivo_espelho') for v in self._mapa_espelhos.values()
            if v.get('arquivo_espelho')
        }

        # Lista todos os JSONs em cache (sem baixar nada novo aqui)
        jsons = sorted(self.espelhos_dir.glob('*.json'))
        novos = [j for j in jsons if j.name not in arquivos_indexados]

        if not novos:
            print(f'  📋  Mapa espelhos já atualizado ({len(self._mapa_espelhos)} registros)')
            return

        print(f'  🔄  Indexando {len(novos)} arquivo(s) de espelhos...')
        inseridos = 0
        for arq in tqdm(novos, desc='Indexando espelhos'):
            orgao = arq.stem.split('_')[0] if '_' in arq.stem else ''
            for item in self._ler_json(arq):
                num_reg = str(item.get('numeroRegistro') or '').strip()
                data_pub_raw = str(item.get('dataPublicacao') or '')
                tipo_decisao = str(item.get('tipoDeDecisao') or '').strip()
                data_pub = _extrair_data_pub_espelho(data_pub_raw)

                if not num_reg or not data_pub or not tipo_decisao:
                    continue
                
                # Filtra a carga de registros usando as tuplas do inicializador
                if not self._passou_filtro_registro(num_reg, data_pub, tipo_decisao):
                    continue

                id_mapa = _gerar_id_mapa(num_reg, data_pub, tipo_decisao)
                id_espelho = str(item.get('id') or '').strip()

                registro = {
                    'id_mapa':          id_mapa,
                    'numero_registro':  num_reg,
                    'data_publicacao':  data_pub,
                    'tipo_decisao':     tipo_decisao,
                    'id_espelho':       id_espelho,
                    'orgao':            orgao,
                    'sigla_classe':     str(item.get('siglaClasse') or ''),
                    'arquivo_espelho':  arq.name,
                }

                if id_mapa in self._mapa_espelhos:
                    self._registrar_duplicado(id_mapa, registro, self._mapa_espelhos[id_mapa], 'espelho')
                else:
                    self._mapa_espelhos[id_mapa] = registro
                    inseridos += 1

        print(f'  ✅  Mapa espelhos: +{inseridos} novos → {len(self._mapa_espelhos)} total')
        self._salvar_mapa_espelhos()

    def _atualizar_mapa_integras(self):
        """Indexa íntegras usando os JSONs de metadados publicados no CKAN.

        Os JSONs de metadados são recursos separados no dataset de íntegras
        (ex: metadados20240110.json). Não é necessário abrir os ZIPs para indexar.
        Cada metadado contém: seqDocumento, numeroRegistro, dataPublicacao (epoch ms),
        tipoDocumento. Com esses campos, geramos o id_mapa e mapeamos o ZIP/TXT.
        """
        from tqdm.auto import tqdm

        # Arquivos de metadados já indexados
        arquivos_indexados = {
            v.get('arquivo_metadados') for v in self._mapa_integras.values()
            if v.get('arquivo_metadados')
        }

        # Lista JSONs de metadados já em cache local
        jsons_locais = sorted(self.metadados_dir.glob('*.json'))
        novos_locais = [j for j in jsons_locais if j.name not in arquivos_indexados]

        # Tenta listar recursos no CKAN para baixar novos metadados
        recursos_meta = self._listar_recursos_metadados()
        if recursos_meta:
            nomes_locais = {j.name for j in jsons_locais}
            para_baixar = [r for r in recursos_meta if r['name'] not in nomes_locais]
            if para_baixar:
                print(f'  🔄  Baixando {len(para_baixar)} JSON(s) de metadados de íntegras...')
                for r in tqdm(para_baixar, desc='Metadados íntegras'):
                    try:
                        self._baixar(r['url'], r['name'], self.metadados_dir, True)
                    except Exception as e:
                        print(f'  ⚠️  Erro ao baixar {r["name"]}: {e}')
                # Reavalia JSONs locais após download
                jsons_locais = sorted(self.metadados_dir.glob('*.json'))
                novos_locais = [j for j in jsons_locais if j.name not in arquivos_indexados]

        if not novos_locais:
            print(f'  📋  Mapa íntegras já atualizado ({len(self._mapa_integras)} registros)')
            return

        # Para calcular o caminho do TXT: {YYYYMMDD}/{seqDocumento}.txt
        # O ZIP correspondente tem nome baseado na data de publicação do metadado
        # ZIPs antigos: 202202.zip (mês inteiro), novos: 20240110.zip (dia)
        # Montamos lookup de ZIPs disponíveis em cache para verificar
        zips_cache = {z.stem: z.name for z in self.integras_dir.glob('*.zip')}

        print(f'  🔄  Indexando {len(novos_locais)} JSON(s) de metadados...')
        inseridos = 0
        for arq_meta in tqdm(novos_locais, desc='Indexando íntegras'):
            try:
                meta = json.loads(arq_meta.read_text('utf-8', errors='replace'))
                if isinstance(meta, dict):
                    meta = [meta]

                # Extrair data base do nome do arquivo para achar o ZIP
                # ex: metadados20240110.json → 20240110 → 20240110.zip
                # ex: metadadosPublicacao202202.json → 202202 → 202202.zip
                nome_base = arq_meta.stem  # metadados20240110 ou metadadosPublicacao202202
                data_zip = re.sub(r'^metadados(?:Publicacao)?', '', nome_base)
                nome_zip = f'{data_zip}.zip' if data_zip else ''

                for item in meta:
                    # Campos com nomenclatura variável entre versões do CKAN
                    num_reg  = str(item.get('numeroRegistro') or '').strip()
                    data_pub = _extrair_data_pub_integra(item.get('dataPublicacao'))
                    tipo_doc = str(item.get('tipoDocumento') or '').strip()
                    # seqDocumento → SeqDocumento (a partir de fev/2024)
                    seq_doc  = item.get('seqDocumento') or item.get('SeqDocumento')
                    ministro = str(item.get('ministro') or item.get('NM_MINISTRO') or '').strip()

                    if not num_reg or not data_pub or not tipo_doc:
                        continue
                    
                    # Filtra a carga de registros usando as tuplas do inicializador
                    if not self._passou_filtro_registro(num_reg, data_pub, tipo_doc):
                        continue

                    if self.documentos and seq_doc:
                        if str(seq_doc).strip() not in self.documentos:
                            continue

                    id_mapa = _gerar_id_mapa(num_reg, data_pub, tipo_doc)

                    # Caminho do TXT: {YYYYMMDD}/{seqDocumento}.txt ou {seqDocumento}.txt
                    arquivo_txt = f'{data_pub}/{seq_doc}.txt'

                    registro = {
                        'id_mapa':             id_mapa,
                        'numero_registro':     num_reg,
                        'data_publicacao':     data_pub,
                        'tipo_decisao':        tipo_doc,
                        'seq_documento':       seq_doc,
                        'arquivo_integra':     nome_zip,
                        'arquivo_txt':         arquivo_txt,
                        'arquivo_metadados':   arq_meta.name,
                        'processo':            str(item.get('processo') or '').strip(),
                        'ministro':            ministro,
                    }

                    if id_mapa in self._mapa_integras:
                        self._registrar_duplicado(id_mapa, registro, self._mapa_integras[id_mapa], 'integra')
                    else:
                        self._mapa_integras[id_mapa] = registro
                        inseridos += 1
            except Exception as e:
                print(f'  ⚠️  Erro ao indexar {arq_meta.name}: {e}')

        print(f'  ✅  Mapa íntegras: +{inseridos} novos → {len(self._mapa_integras)} total')
        self._salvar_mapa_integras()

    def _listar_recursos_metadados(self) -> list[dict]:
        """Lista os JSONs de metadados publicados no dataset de íntegras do CKAN."""
        recursos = []
        try:
            for r in self._listar_recursos(DATASET_TEXTOS_PADRAO):
                nome = r.get('name', '')
                fmt  = r.get('format', '').upper()
                if fmt == 'JSON' or nome.endswith('.json'):
                    # Normaliza nome para ter extensão .json
                    if not nome.endswith('.json'):
                        nome = nome + '.json'
                    recursos.append({'name': nome, 'url': r['url']})
        except Exception as e:
            print(f'  ⚠️  Erro ao listar metadados de íntegras no CKAN: {e}')
        return recursos

    # ══════════════════════════════════════════════════════════════════════════
    # Consultas com base nos mapas
    # ══════════════════════════════════════════════════════════════════════════

    def consultar_mapa(self, filtros: Optional[dict] = None) -> list[dict]:
        """Retorna registros do mapa de espelhos que satisfazem os filtros configurados.

        Combina os filtros do construtor (anos, orgaos, classes, registros,
        documentos) com filtros adicionais opcionais passados como dict.
        Retorna lista de registros do mapa (cada um possui id_mapa, id_espelho, etc.).
        """
        resultados = []
        for id_mapa, reg in self._mapa_espelhos.items():
            # Filtro por ano
            if self.anos:
                data_pub = reg.get('data_publicacao', '')
                if len(data_pub) >= 4 and data_pub[:4] not in self.anos:
                    continue
            # Filtro por órgão
            orgaos_siglas = {s for s, _ in self.orgaos}
            if orgaos_siglas != {s for s, _ in DATASETS_ESPELHOS_PADRAO}:
                if reg.get('orgao', '') not in orgaos_siglas:
                    continue
            # Filtro por classe
            if self.classes:
                sigla = reg.get('sigla_classe', '').upper()
                if not any(re.search(rf'\b{re.escape(c)}\b', sigla) for c in self.classes):
                    continue
            # Filtro por registro (pode ser str, tupla de 2 - com data, ou tupla de 3 - com tipo)
            if self.registros:
                reg_num = str(reg.get('numero_registro', ''))
                reg_data = str(reg.get('data_publicacao', ''))
                reg_tipo = str(reg.get('tipo_decisao', ''))
                if not self._passou_filtro_registro(reg_num, reg_data, reg_tipo):
                    continue

            # Filtro por documento (seq_documento) no espelho ou na íntegra
            if self.documentos:
                seq_esp = str(reg.get('seq_documento', '')).strip()
                integra = self._mapa_integras.get(id_mapa, {})
                seq_int = str(integra.get('seq_documento', '')).strip()
                if seq_esp not in self.documentos and seq_int not in self.documentos:
                    continue
            # Filtros adicionais
            if filtros:
                skip = False
                for k, v in filtros.items():
                    if reg.get(k) != v:
                        skip = True
                        break
                if skip:
                    continue
            resultados.append(reg)
        return resultados

    def cruzar_espelhos_integras(self) -> list[dict]:
        """Cruza mapa de espelhos com mapa de íntegras pelo id_mapa.

        Retorna lista de dicts com dados combinados (espelho + íntegra),
        já aplicando todos os filtros configurados na classe.
        """
        espelhos_filtrados = self.consultar_mapa()
        resultado = []
        for reg_espelho in espelhos_filtrados:
            id_mapa = reg_espelho['id_mapa']
            reg_integra = self._mapa_integras.get(id_mapa, {})
            combinado = {**reg_espelho}
            if reg_integra:
                combinado['seq_documento']   = reg_integra.get('seq_documento')
                combinado['arquivo_integra'] = reg_integra.get('arquivo_integra', '')
                combinado['arquivo_txt']     = reg_integra.get('arquivo_txt', '')
                combinado['tem_integra']     = True
            else:
                combinado['seq_documento']   = None
                combinado['arquivo_integra'] = ''
                combinado['arquivo_txt']     = ''
                combinado['tem_integra']     = False
            resultado.append(combinado)
        return resultado

    # ══════════════════════════════════════════════════════════════════════════
    # Métodos de alto nível
    # ══════════════════════════════════════════════════════════════════════════

    def obter_integras(self) -> dict[str, str]:
        """Obtém íntegras indexadas por id_mapa, usando o cruzamento dos mapas.

        Retorna dict: id_mapa → texto integral.
        """
        cruzados = self.cruzar_espelhos_integras()
        itens = [c for c in cruzados if c.get('tem_integra')]
        if not itens:
            print('⚠️  Nenhum item com íntegra encontrado nos mapas.')
            return {}

        from tqdm.auto import tqdm
        integras: dict[str, str] = {}

        # Agrupa por arquivo ZIP para abrir cada ZIP apenas uma vez
        por_zip: dict[str, list[dict]] = {}
        for item in itens:
            arq = item.get('arquivo_integra', '')
            if arq:
                por_zip.setdefault(arq, []).append(item)

        for nome_zip, itens_zip in tqdm(por_zip.items(), desc='Extraindo íntegras'):
            caminho_zip = self.integras_dir / nome_zip
            if not caminho_zip.is_file():
                print(f'  ⚠️  ZIP não encontrado em cache: {nome_zip}')
                continue
            try:
                with zipfile.ZipFile(caminho_zip) as zf:
                    # Monta lookup de TXTs por stem (seq_documento) para busca flexível
                    txt_por_seq: dict[str, str] = {}
                    for entry in zf.namelist():
                        if entry.endswith('.txt'):
                            txt_por_seq[Path(entry).stem] = entry

                    for item in itens_zip:
                        seq = str(item.get('seq_documento', ''))
                        txt_path = item.get('arquivo_txt', '')
                        # Tenta: 1) caminho exato, 2) busca por seq no lookup
                        if txt_path and txt_path in zf.namelist():
                            integras[item['id_mapa']] = zf.read(txt_path).decode('utf-8', errors='replace')
                        elif seq in txt_por_seq:
                            integras[item['id_mapa']] = zf.read(txt_por_seq[seq]).decode('utf-8', errors='replace')
            except Exception as e:
                print(f'  ⚠️  Erro ao ler {nome_zip}: {e}')

        print(f'Íntegras extraídas: {len(integras)} / {len(itens)}')
        return integras

    def obter_espelhos(self) -> dict[str, dict]:
        """Obtém dados completos dos espelhos, indexados por id_mapa.

        Aplica os filtros configurados, lê os JSONs necessários e retorna
        dict: id_mapa → {campos do espelho}.
        """
        items_filtrados = self.consultar_mapa()
        if not items_filtrados:
            print('⚠️  Nenhum espelho encontrado com os filtros informados.')
            return {}

        from tqdm.auto import tqdm
        espelhos: dict[str, dict] = {}

        # Agrupa por arquivo para ler cada JSON uma única vez
        por_arquivo: dict[str, list[dict]] = {}
        for item in items_filtrados:
            arq = item.get('arquivo_espelho', '')
            if arq:
                por_arquivo.setdefault(arq, []).append(item)

        ids_alvo = {item['id_mapa'] for item in items_filtrados}

        for nome_arq, itens_arq in tqdm(por_arquivo.items(), desc='Lendo espelhos'):
            caminho = self.espelhos_dir / nome_arq
            if not caminho.is_file():
                continue

            ids_neste_arquivo = {it['id_mapa'] for it in itens_arq}
            for item_json in self._ler_json(caminho):
                num_reg = str(item_json.get('numeroRegistro') or '').strip()
                data_pub = _extrair_data_pub_espelho(str(item_json.get('dataPublicacao') or ''))
                tipo = str(item_json.get('tipoDeDecisao') or '').strip()
                if not num_reg or not data_pub or not tipo:
                    continue
                id_mapa = _gerar_id_mapa(num_reg, data_pub, tipo)
                if id_mapa not in ids_neste_arquivo:
                    continue

                reg = {c: self._formatar_valor(item_json.get(c)) for c in self.colunas}
                reg['id_mapa'] = id_mapa
                espelhos[id_mapa] = reg

        print(f'Espelhos extraídos: {len(espelhos)} / {len(ids_alvo)}')
        return espelhos

    def gerar_dataset_espelhos(
        self,
        caminho_saida: str | Path,
        incluir_integras: bool = False,
        incluir_ementas: bool = True,
        incluir_decisoes: bool = True,
    ):
        """Gera um parquet com espelhos + opcionalmente íntegras, usando os mapas.

        Aplica automaticamente os filtros configurados no construtor.
        Retorna o DataFrame gerado.
        """
        import pandas as pd
        from tqdm.auto import tqdm

        caminho_saida = Path(caminho_saida)
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)

        # ── 1. Cruzar mapas e obter espelhos ──────────────────────────────────
        cruzados = self.cruzar_espelhos_integras()
        if not cruzados:
            print('⚠️  Nenhum registro encontrado com os filtros informados.')
            return None

        print(f'Registros cruzados (espelho × íntegra): {len(cruzados)}')

        # Agrupa por arquivo de espelho para ler cada JSON uma vez
        por_arquivo: dict[str, list[dict]] = {}
        for item in cruzados:
            arq = item.get('arquivo_espelho', '')
            if arq:
                por_arquivo.setdefault(arq, []).append(item)

        registros: list[dict] = []
        ids_alvo = {c['id_mapa'] for c in cruzados}

        for nome_arq, itens in tqdm(por_arquivo.items(), desc='Espelhos'):
            caminho = self.espelhos_dir / nome_arq
            if not caminho.is_file():
                continue
            ids_neste = {it['id_mapa'] for it in itens}
            cruzados_map = {it['id_mapa']: it for it in itens}

            for item_json in self._ler_json(caminho):
                num_reg = str(item_json.get('numeroRegistro') or '').strip()
                data_pub_raw = str(item_json.get('dataPublicacao') or '')
                data_pub = _extrair_data_pub_espelho(data_pub_raw)
                tipo = str(item_json.get('tipoDeDecisao') or '').strip()
                if not num_reg or not data_pub or not tipo:
                    continue
                id_mapa = _gerar_id_mapa(num_reg, data_pub, tipo)
                if id_mapa not in ids_neste:
                    continue

                reg = {c: self._formatar_valor(item_json.get(c)) for c in self.colunas}
                if incluir_ementas:
                    reg['ementa'] = self._formatar_valor(item_json.get('ementa'))
                if incluir_decisoes:
                    reg['decisao'] = self._formatar_valor(item_json.get('decisao'))

                cruzado = cruzados_map[id_mapa]
                reg['id_mapa']                = id_mapa
                reg['orgao']                  = cruzado.get('orgao', '')
                reg['data_publicacao_iso']     = data_pub
                reg['seq_documento_acordao']   = cruzado.get('seq_documento')
                reg['tem_integra']            = cruzado.get('tem_integra', False)
                registros.append(reg)

        print(f'\nRegistros extraídos: {len(registros)}')
        if not registros:
            print('⚠️  Nenhum registro extraído.')
            return None

        df = pd.DataFrame(registros)
        df = df.drop_duplicates(subset=['id_mapa']).reset_index(drop=True)

        # ── 2. Íntegras (opcional) ────────────────────────────────────────────
        if incluir_integras:
            integras = self.obter_integras()
            df['integra'] = df['id_mapa'].map(integras).fillna('')

        # ── 3. Salvamento e resumo ────────────────────────────────────────────
        df.to_parquet(caminho_saida, index=False)
        self._imprimir_resumo(df, caminho_saida, incluir_integras)
        return df

    # ══════════════════════════════════════════════════════════════════════════
    # Listagem e download
    # ══════════════════════════════════════════════════════════════════════════

    def listar_recursos_espelhos(
        self,
        datasets: Optional[list[tuple[str, str]]] = None,
        anos: Optional[set[str]] = None,
    ) -> list[dict]:
        """Lista recursos JSON de espelhos por órgão julgador."""
        ds   = datasets or self.orgaos
        anos = anos if anos is not None else self.anos
        recursos: list[dict] = []
        for orgao, dataset_id in ds:
            try:
                for r in self._listar_recursos(dataset_id):
                    nome = r.get('name', '')
                    fmt  = r.get('format', '').upper()
                    if not (nome.lower().endswith('.json') or fmt == 'JSON'):
                        continue
                    if anos:
                        m = re.match(r'^(\d{4})\d{4}\.json$', nome, re.IGNORECASE)
                        if not m or m.group(1) not in anos:
                            continue
                    recursos.append({
                        'orgao'      : orgao,
                        'name'       : f'{orgao}_{nome}',
                        'url'        : r['url'],
                        'resource_id': r.get('id', ''),
                    })
            except Exception as e:
                print(f'  ⚠️  Erro ao listar espelhos de {orgao}: {e}')
        return recursos

    def listar_recursos_zip(
        self,
        dataset_id: str = DATASET_TEXTOS_PADRAO,
        anos: Optional[set[str]] = None,
    ) -> list[dict]:
        """Lista recursos ZIP de íntegras, filtrados por ano."""
        anos = anos if anos is not None else self.anos
        recursos: list[dict] = []
        try:
            for r in self._listar_recursos(dataset_id):
                nome = r.get('name', '')
                fmt  = r.get('format', '').upper()
                if not (nome.lower().endswith('.zip') or fmt == 'ZIP'):
                    continue
                if anos and not any(nome.startswith(a) for a in anos):
                    continue
                recursos.append({'name': nome, 'url': r['url']})
        except Exception as e:
            print(f'  ⚠️  Erro ao listar ZIPs: {e}')
        return recursos

    def baixar_espelhos(self):
        """Baixa todos os espelhos necessários (conforme filtros)."""
        from tqdm.auto import tqdm
        recursos = self.listar_recursos_espelhos()
        print(f'Baixando {len(recursos)} arquivo(s) de espelhos...')
        for r in tqdm(recursos, desc='Espelhos'):
            try:
                self._baixar(r['url'], r['name'], self.espelhos_dir, self.atualizar_cache_e_mapas)
            except Exception as e:
                print(f'  ⚠️  {r["name"]}: {e}')

    def baixar_integras(self):
        """Baixa todos os ZIPs de íntegras necessários (conforme filtros)."""
        from tqdm.auto import tqdm
        recursos = self.listar_recursos_zip()
        print(f'Baixando {len(recursos)} ZIP(s) de íntegras...')
        for r in tqdm(recursos, desc='ZIPs'):
            try:
                self._baixar(r['url'], r['name'], self.integras_dir, self.atualizar_cache_e_mapas)
            except Exception as e:
                print(f'  ⚠️  {r["name"]}: {e}')

    def baixar_espelho(self, recurso: dict) -> Path:
        """Baixa um recurso de espelho para o cache."""
        return self._baixar(recurso['url'], recurso['name'],
                            self.espelhos_dir, self.atualizar_cache_e_mapas)

    def baixar_zip(self, recurso: dict) -> Path:
        """Baixa um ZIP de íntegras para o cache."""
        return self._baixar(recurso['url'], recurso['name'],
                            self.integras_dir, self.atualizar_cache_e_mapas)

    # ══════════════════════════════════════════════════════════════════════════
    # Métodos internos
    # ══════════════════════════════════════════════════════════════════════════

    def _listar_recursos(self, dataset_id: str) -> list[dict]:
        """Retorna a lista de recursos de um dataset CKAN."""
        url = f'{self.base_url}/api/3/action/package_show'
        r = requests.get(url, params={'id': dataset_id}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()['result'].get('resources', [])

    def _baixar(self, url: str, nome_arquivo: str, pasta: Path, permitir: bool) -> Path:
        """Baixa o arquivo para `pasta` usando cache local."""
        caminho = Path(pasta) / nome_arquivo
        if caminho.is_file():
            print(f'  [cache] {nome_arquivo:<55}', end='\r', flush=True)
            return caminho
        if not permitir:
            raise FileNotFoundError(
                f'[ignorado] {nome_arquivo} não está em cache e download está desabilitado'
            )
        print(f'  [↓]     {nome_arquivo:<55}', end='\r', flush=True)
        with requests.get(url, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            with open(caminho, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        return caminho

    @staticmethod
    def _ler_json(caminho: Path) -> list[dict]:
        """Lê JSON com tratamento de encoding. Retorna lista de dicts."""
        for enc in ('utf-8', 'latin-1'):
            try:
                with open(caminho, encoding=enc) as f:
                    dados = json.load(f)
                return dados if isinstance(dados, list) else [dados]
            except UnicodeDecodeError:
                continue
            except json.JSONDecodeError:
                conteudo = caminho.read_text(encoding='utf-8', errors='replace')
                if 'sem lançamentos' in conteudo.lower():
                    return []
                raise
        return []

    @staticmethod
    def _formatar_valor(v):
        """Normaliza strings e arredonda floats."""
        if isinstance(v, str):
            return v.replace('\n', ' ').replace('\r', ' ').strip()
        if isinstance(v, float):
            return round(v, 3)
        return v

    @staticmethod
    def _imprimir_resumo(df, caminho_saida: Path, incluir_integras: bool):
        """Imprime estatísticas do dataset gerado."""
        sep = '─' * 55
        total = len(df)
        print(sep)
        print(f'  📄  {caminho_saida}')
        print(f'      {caminho_saida.stat().st_size / 1024**2:.2f} MB | {len(df.columns)} colunas | {total} registros')
        print(sep)
        if incluir_integras and 'integra' in df.columns:
            com = df['integra'].str.len().gt(0).sum()
            print(f'  Com íntegra  : {com:>6}  ({com/total*100:.1f}%)')
            print(f'  Sem íntegra  : {total - com:>6}  ({(total-com)/total*100:.1f}%)')
            print(sep)
        if 'data_publicacao_iso' in df.columns:
            df['_ano'] = df['data_publicacao_iso'].str[:4]
            print('  📅  Por ano de publicação:')
            for ano, grp in df.groupby('_ano'):
                ct = grp['integra'].str.len().gt(0).sum() if 'integra' in grp.columns else 0
                lbl = f' | íntegra: {ct}' if incluir_integras else ''
                print(f'      {ano} → {len(grp):>5} registros{lbl}')
            df.drop(columns=['_ano'], inplace=True)
            print(sep)
        if 'siglaClasse' in df.columns:
            top = df['siglaClasse'].value_counts().head(10)
            print('  ⚖️  Top classes:')
            for cls, cnt in top.items():
                print(f'      {str(cls):<35} {cnt:>5}')
            print(sep)
        if 'tem_integra' in df.columns:
            ci = df['tem_integra'].sum()
            print(f'  🔗  Com correspondência íntegra no mapa: {ci} / {total}')
            print(sep)
        print('  ✅  Concluído!')

    @staticmethod
    def exibir_amostra(df, n: int = 2, titulo: str = 'Amostra'):
        """Exibe até n registros do DataFrame de forma legível."""
        import pandas as pd
        if df is None or df.empty:
            print('⚠️  Nenhum dado disponível.')
            return
        print(f'\n{titulo} ({len(df)} registros totais, exibindo {min(n, len(df))}):')        
        print('═' * 65)
        col_integra = 'integra' if 'integra' in df.columns else None
        col_ementa  = 'ementa'  if 'ementa'  in df.columns else None
        amostra = df.head(n)
        for i, row in amostra.iterrows():
            excluir = {'integra', 'ementa', 'decisao'}
            dados = [
                f'  {str(c).ljust(28)}: {v}'
                for c, v in row.items()
                if c not in excluir and str(v) not in ('', '[]', 'None')
            ]
            dados.sort()
            [print(d) for d in dados]
            if col_ementa and pd.notna(row.get(col_ementa)) and str(row[col_ementa]):
                txt = str(row[col_ementa])[:200] + '[..]' + str(row[col_ementa])[200:]
                print(f'  {"EMENTA:":12}: {txt}')
            if col_integra and pd.notna(row.get(col_integra)) and str(row[col_integra]):
                txt = str(row[col_integra])[:200] + '[..]' + str(row[col_integra])[200:]
                print(f'  {"ÍNTEGRA:":12}: {txt}')
            print('─' * 65)

##############################################################################
####### EXEMPLOS
##############################################################################

class ExemplosCKan():

    @classmethod
    def exemplo1(cls, atualizar_cache_e_mapas):
        print('=== Exemplo 1: construir mapas + dataset Penal (2024) ===\n')

        ckan = UtilCkan(
            anos   = {'2024','2024'},
            orgaos = ['T5', 'T6', 'S3'],
            atualizar_cache_e_mapas = atualizar_cache_e_mapas,
        )

        # Mostra estatísticas dos mapas
        cruzados = ckan.cruzar_espelhos_integras()
        com_integra = sum(1 for c in cruzados if c['tem_integra'])
        print(f'\nCruzamento: {len(cruzados)} espelhos | {com_integra} com íntegra disponível')

        # Gera dataset
        df = ckan.gerar_dataset_espelhos(
            caminho_saida = Path('../data/exemplo.parquet'),
            incluir_integras = False,
            incluir_ementas = True,
            incluir_decisoes = False,
        )

        # Duplicados
        dups = ckan.obter_duplicados()
        if dups:
            print(f'\n⚠️  {len(dups)} id_mapa(s) com duplicatas')
            for id_mapa, ocorrencias in list(dups.items())[:3]:
                print(f'  {id_mapa}: {len(ocorrencias)} duplicata(s)')

        print('#' * 55)
        cls.print_df(df, ckan._mapa_espelhos, ckan._mapa_integras)


    @classmethod
    def exemplo2(cls, num_registro, atualizar_cache_e_mapas):
        print('=== Exemplo 2: construir mapas + dataset com um número de registro específico ===\n')
        num_registro = num_registro or '202201546162'
        ckan2 = UtilCkan(
            registros= {num_registro},
            atualizar_cache_e_mapas = atualizar_cache_e_mapas,
        )

        df = ckan2.gerar_dataset_espelhos(
            caminho_saida  = Path('../data/exemplo_ementas.parquet'),
            incluir_integras = True,
            incluir_ementas = True,
            incluir_decisoes = True,
        )
        cls.print_df(df, ckan2._mapa_espelhos, ckan2._mapa_integras)

    @classmethod
    def print_df(cls, df, mapa_espelhos, mapa_integras):
        if df is None:
            print('Nenhum df informado')
            return
        if len(df) == 0:
            print('Nenhum registro encontrado')
            return
        print(df.head())
        item = df.iloc[0]
        print('-' * 55)
        print(f'Exemplo de ementa ({item.get("id_mapa", "")}):')
        print(f'>>> EMENTA: {str(item["ementa"])[:300]} [...]')

        print('-' * 55)
        print(f'Exemplo de decisão ({item.get("id_mapa", "")}):')
        print(f'>>> DECISÃO: {str(item["decisao"])[:300]} [...]')

        print('-' * 55)
        print(f'Exemplo de integra ({item.get("id_mapa", "")}):')
        print(f'>>> ÍNTEGRA: {str(item["integra"])[:200]} [...] {str(item["integra"])[-100:]}')

        outros_dados = {c:v for c,v in item.items() if c not in {'id_mapa', 'ementa', 'decisao', 'integra'}}
        print('-' * 55)
        print(f'Outros dados ({item.get("id_mapa", "")}):')
        #print(json.dumps(outros_dados, indent=2, ensure_ascii=False))
        print(outros_dados)
        print('-' * 55)
        print(f'Mapa do espelho: {mapa_espelhos[item.get("id_mapa", "")]}')
        print('-' * 55)
        print(f'Mapa da integra: {mapa_integras[item.get("id_mapa", "")]}')
    

if __name__ == '__main__':
    """Exemplos de uso — execução direta para teste rápido."""
    from pathlib import Path

    atualizar_mapas_e_cache = True
    # Exemplo 1: construir mapas e gerar dataset Penal (2024)
    #ExemplosCKan.exemplo1(atualizar_mapas_e_cache)

    # Exemplo 2: construir mapas e gerar dataset com um número de registro específico
    ExemplosCKan.exemplo2(num_registro = '202302829818', atualizar_cache_e_mapas = atualizar_mapas_e_cache)

