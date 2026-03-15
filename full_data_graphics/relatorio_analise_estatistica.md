# Relatório de Análise Estatística — Comparação Intra-Família

## 1. Desempenho (Ranking)

Ranking dos modelos ordenado pela média de desempenho F1 da avaliação LLM-as-a-Judge (decrescente).

A média e o desvio padrão (σ) indicam a tendência central e a dispersão dos scores F1. A mediana complementa a análise por ser robusta a outliers. O suporte indica o número de documentos avaliados para cada modelo.

| Pos | Família | Modelo | Média | σ | Mediana | Suporte | Custo Médio |
|---|---|---|---|---|---|---|---|
| 1 | GPT-5 | base_gpt5 | 0.8918 | 0.0516 | 0.9028 | 1216 | 37.4274 |
| 2 | GPT-5 | agentes_gpt5 | 0.8724 | 0.0401 | 0.8772 | 779 | 83.0113 |
| 3 | Gemma 3 12b | base_gemma3(12) | 0.6432 | 0.0996 | 0.6375 | 1216 | 36.4065 |
| 4 | Gemma 3 12b | agentes_gemma3(12) | 0.6183 | 0.1057 | 0.6242 | 1210 | 89.6801 |
| 5 | Gemma 3 27b | base_gemma3(27) | 0.7260 | 0.0989 | 0.7266 | 1216 | 36.3450 |
| 6 | Gemma 3 27b | agentes_gemma3(27) | 0.6822 | 0.0933 | 0.6844 | 1147 | 65.9864 |

## 2. Normalidade dos Deltas (Shapiro-Wilk)

Verifica se as diferenças (Δ = Modelo 2 − Modelo 1) de cada par intra-família seguem distribuição normal.

Se p > 0,05, não se rejeita a normalidade e testes paramétricos (ex: t de Student) seriam aplicáveis. Se p ≤ 0,05, a distribuição dos deltas não é normal e testes não-paramétricos como Wilcoxon são mais adequados. Com amostras grandes (n > 30), o Wilcoxon é robusto e geralmente preferido por não assumir normalidade.

| Família | Modelo 1 | Modelo 2 | n | Shapiro W | p-valor | Normal (p>0.05) |
|---|---|---|---|---|---|---|
| GPT-5 | base_gpt5 | agentes_gpt5 | 779 | 0.9694 | 1.07e-11 | Não |
| Gemma 3 12b | base_gemma3(12) | agentes_gemma3(12) | 1210 | 0.9988 | 0.5864 | Sim |
| Gemma 3 27b | base_gemma3(27) | agentes_gemma3(27) | 1147 | 0.9977 | 0.1167 | Sim |

## 3. Teste de Wilcoxon (Signed-Rank)

Teste não-paramétrico para amostras pareadas, aplicado a cada par de modelos dentro da mesma família.

A diferença é calculada como Δ = Modelo 2 − Modelo 1: valores positivos indicam que o Modelo 2 superou o Modelo 1. Um p-valor < 0,05 indica rejeição da hipótese nula de igualdade (diferença estatisticamente significativa). O Cohen's d mede a magnitude prática do efeito: Insignificante (|d| < 0,10), Pequeno (0,10–0,30), Médio (0,30–0,50), Grande (≥ 0,50).

| Família | Modelo 1 | Modelo 2 | n | Média M1 | Média M2 | Δ | p-valor | Sig. | Cohen's d | Efeito |
|---|---|---|---|---|---|---|---|---|---|---|
| GPT-5 | base_gpt5 | agentes_gpt5 | 779 | 0.8930 | 0.8724 | -0.0206 | 1.19e-24 | Sim | -0.3263 | Médio |
| Gemma 3 12b | base_gemma3(12) | agentes_gemma3(12) | 1210 | 0.6428 | 0.6183 | -0.0245 | 2.31e-13 | Sim | -0.2195 | Pequeno |
| Gemma 3 27b | base_gemma3(27) | agentes_gemma3(27) | 1147 | 0.7321 | 0.6822 | -0.0499 | 2.34e-44 | Sim | -0.4519 | Médio |

## 4. Eficiência e Custos

Compara o custo-benefício (eficiência = qualidade / custo) entre cada par de modelos da mesma família.

Δ Eficiência positivo indica que o Modelo 2 é mais eficiente que o Modelo 1. Δ Custo positivo significa que o Modelo 2 é mais caro. O cenário ideal é Δ Valor positivo com Δ Custo negativo (melhor qualidade, menor custo).

| Família | Modelo 1 | Modelo 2 | Custo M1 | Custo M2 | Δ Custo (%) | Δ Valor (%) | Efic. M1 | Efic. M2 | Δ Efic. (%) |
|---|---|---|---|---|---|---|---|---|---|
| GPT-5 | base_gpt5 | agentes_gpt5 | 37.4902 | 83.0113 | 121.42% | -2.31% | 0.0238 | 0.0105 | -55.88% |
| Gemma 3 12b | base_gemma3(12) | agentes_gemma3(12) | 36.4093 | 89.6801 | 146.31% | -3.81% | 0.0177 | 0.0069 | -60.95% |
| Gemma 3 27b | base_gemma3(27) | agentes_gemma3(27) | 35.9953 | 65.9864 | 83.32% | -6.82% | 0.0203 | 0.0103 | -49.17% |