# Comparação base_gpt5 vs Modelos

**Data de geração:** 08/03/2026 00:28

---
<!-- SECTION: OVERVIEW -->
## 📋 Visão Geral

**Experimento:** Comparação base_gpt5 vs Modelos

**Objetivo:** Análise comparativa configurada via YAML.

**Escopo da análise:**
- **Origem:** `id`
- **Destinos:** 6 modelos/abordagens
  - `base_gpt5`
  - `agentes_gpt5`
  - `base_gemma3(12)`
  - `agentes_gemma3(12)`
  - `base_gemma3(27)`
  - `agentes_gemma3(27)`
- **Documentos analisados:** 732
- **Campos comparados:** 7
  - `teseJuridica`
  - `notas`
  - `termosAuxiliares`
  - `informacoesComplementares`
  - `jurisprudenciaCitada`
  - `referenciasLegislativas`
  - `tema`

---

<!-- /SECTION: OVERVIEW -->
<!-- SECTION: CONFIG -->
## ⚙️ Configuração da Análise

### Parâmetros Gerais
- **Nível de campos:** 1 (1=raiz, 2=raiz+aninhado)
- **Padronização de símbolos:** Sim
- **ROUGE Stemmer:** Sim

### Métricas Utilizadas

**Filosofia de seleção:**
1. **BERTScore** → Similaridade semântica profunda (textos longos)
2. **ROUGE-L** → Sequências estruturadas (ordem importa)
3. **ROUGE-2** → Precisão de bigramas (fraseamento técnico)
4. **ROUGE-1** → Termos individuais (palavras-chave)
5. **Levenshtein** → Distância de edição (textos curtos exatos)

### Distribuição de Métricas por Campo

| Campo | Métricas |
|-------|----------|
| `informacoesComplementares` | BERTScore, ROUGE-L |
| `jurisprudenciaCitada` | BERTScore, ROUGE-L, ROUGE-2 |
| `notas` | BERTScore, ROUGE-L |
| `referenciasLegislativas` | BERTScore, ROUGE-L |
| `tema` | BERTScore, ROUGE-2 |
| `termosAuxiliares` | BERTScore, ROUGE-2 |
| `teseJuridica` | BERTScore, ROUGE-L |

**Campos especiais:**
- `(global)`: Visão geral do documento completo
- `(estrutura)`: Acurácia estrutural (campos presentes/ausentes)

---

<!-- /SECTION: CONFIG -->
<!-- SECTION: RESULTS -->
## 📊 Resultados Principais

### 🏆 Melhor Modelo

- **Modelo:** `agentes_gpt5`
- **Métrica:** (global)_sbert_F1 (ROUGE2)
- **F1-Score:** 0.8950

### F1-Score Global por Técnica

**BERTScore:**

| Modelo | Mean | Median | Std |
|--------|------|--------|-----|
| agentes_gpt5 | 0.8670 | 0.8720 | 0.0290 |
| base_gemma3(27) | 0.8480 | 0.8520 | 0.0380 |
| base_gemma3(12) | 0.8430 | 0.8450 | 0.0310 |
| agentes_gemma3(27) | 0.8410 | 0.8440 | 0.0340 |
| agentes_gemma3(12) | 0.8250 | 0.8290 | 0.0360 |

**ROUGE-L:**

| Modelo | Mean | Median | Std |
|--------|------|--------|-----|
| agentes_gpt5 | 0.5600 | 0.5620 | 0.0810 |
| base_gemma3(12) | 0.5120 | 0.5160 | 0.0850 |
| agentes_gemma3(27) | 0.5120 | 0.5110 | 0.0700 |
| base_gemma3(27) | 0.5080 | 0.5130 | 0.0950 |
| agentes_gemma3(12) | 0.4970 | 0.5000 | 0.0760 |

**ROUGE2:**

| Modelo | Mean | Median | Std |
|--------|------|--------|-----|
| agentes_gpt5 | 0.8950 | 0.9000 | 0.0300 |
| base_gemma3(27) | 0.8730 | 0.8740 | 0.0310 |
| agentes_gemma3(27) | 0.8700 | 0.8730 | 0.0310 |
| base_gemma3(12) | 0.8620 | 0.8630 | 0.0280 |
| agentes_gemma3(12) | 0.8580 | 0.8590 | 0.0300 |

---

<!-- /SECTION: RESULTS -->
<!-- SECTION: OBSERVABILIDADE -->
## 📊 Observabilidade

**Métricas de execução:**
- **SEG** - Tempo de execução em segundos
- **REV** - Número de revisões/tentativas realizadas
- **IT** - Iterações executadas no processamento
- **AGT** - Número de agentes utilizados
- **QTD** - Quantidade de campos preenchidos (somente origem)
- **BYTES** - Tamanho dos dados por campo em bytes (somente origem)
- **OK** - Status de sucesso da execução (0=erro, 1=sucesso)

**Gráficos gerados:** 0 boxplots

**Aba no Excel:**
- `Observabilidade`: Métricas de execução por modelo/agente

---

<!-- /SECTION: OBSERVABILIDADE -->
<!-- SECTION: LLM_EVAL -->
## 🤖 Avaliação LLM (LLM as a Judge)

**Escopo:**
- Avaliação global: ✅ Sim
- Avaliação por campo: ✅ Sim

**Métricas calculadas:** F1, P, R, explicacao

**Gráficos gerados:** 0 boxplots

**Abas no Excel:**
- `Avaliação LLM`: Métricas globais por modelo
- `Avaliação LLM Campos`: Métricas detalhadas por campo

---

<!-- /SECTION: LLM_EVAL -->
<!-- SECTION: FOOTER -->
## 📁 Arquivos Gerados

- `comparacao_extracoes.xlsx`
- `comparacao_extracoes.csv`
- `comparacao_extracoes.estatisticas.csv`

---

**Última atualização:** 08/03/2026 00:28

<!-- /SECTION: FOOTER -->
