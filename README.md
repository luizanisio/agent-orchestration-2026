# JAMEX: Judicial Multi-Agent Metadata Extraction

## PROPOR 2026

The **17th International Conference on Computational Processing of Portuguese (PROPOR 2026)** is the main scientific meeting in the area of language and speech technologies for the Portuguese/Galician language. The 2026 edition will be held in **Salvador, Brazil, from April 13–16, 2026**.
PROPOR is a biennial event hosted alternately in Brazil and Portugal (and now Galicia), with a history spanning since 1993. More information at [propor2026.ufba.br](https://propor2026.ufba.br/) and [propor.org](https://propor.org).
> Replication package for the paper published at **PROPOR 2026** — *17th International Conference on Computational Processing of Portuguese*.

📄 **Paper:** _in progress_

---

## Abstract

This work proposes and evaluates **JAMEX** (Judicial Multi-Agent Metadata Extraction), a multi-agent pipeline for extracting structured metadata from Brazilian court decisions (*Espelho do Acórdão*), and compares it against a strong single-prompt baseline under an IR-only setting.

We first ran a pilot on 300 decisions and then re-executed the experiment on a stratified dataset of *n* = 1,225; only 735 instances were completed by all evaluated models, so paired comparisons use this common set (*n* = 735). Across re-executions, the accuracy impact of agents was strategy-dependent: GPT-5 improves in multiple agentic strategies but not across all orchestration variants, while smaller models (Gemma 3 12B/27B) show no robust gains and reduce the comparable set due to non-completion. Orchestration refinements motivated by agent design literature (memory, planning, directed review) improved traceability, but performance remained sensitive to task decomposition and context fragmentation. Overall, JAMEX increases token usage and operational complexity, so deployment must balance accuracy, completion reliability, and cost for Portuguese legal metadata extraction.

---

## Overview

**JAMEX** is a multi-agent orchestration pipeline for structured metadata extraction from Brazilian Portuguese appellate court decisions (*acórdãos*). It decomposes the extraction task across specialist agents with explicit planning, dependency-aware execution, schema validation, and directed review — communicating exclusively through JSON objects for auditability and reproducibility.

This repository contains all code used in the experiments reported in the paper, including dataset preparation, the baseline single-prompt approach, the JAMEX pipeline, and the evaluation protocol.

---

## Experimental Setup

| Component         | Specification                                      |
|-------------------|----------------------------------------------------|
| CPU               | Intel® Core™ i7-13700T (13th Gen) @ 1.40 GHz      |
| RAM               | 32 GB DDR5 (usable: 31.6 GB)                       |
| Storage           | SSD 954 GB                                         |
| OS                | Windows 11 Enterprise 24H2 + WSL2 (Debian 11)      |
| Python            | 3.13                                               |
| Models evaluated  | GPT-5 (OpenAI), Gemma 3 12B, Gemma 3 27B           |

---

## Models

Three LLMs were evaluated under both the baseline and JAMEX strategies:

- **GPT-5** (OpenAI, proprietary) — API access, context window 256k tokens, medium reasoning effort for LLM-as-a-Judge and low reasoning effort for agents/baseline.
- **Gemma 3 12B** (Google DeepMind, open weights) — optimized for GPU/TPU execution, 128k context window.
- **Gemma 3 27B** (Google DeepMind, open weights) — same family, larger capacity.

---

## Dataset

Experiments were conducted on a stratified sample of **n = 1,225** Criminal Law appellate decisions (*acórdãos*) from the **Superior Tribunal de Justiça (STJ)** official open data portal, covering the period January 1, 2023 – December 31, 2024.

A semantic diversity filter was applied using cosine similarity (θ = 0.15) on domain-specific embeddings to reduce near-duplicate documents and increase corpus variance.

**Data availability:** The dataset is **not distributed directly** in this repository. Instead, a data extraction script is provided that downloads decisions directly from the [STJ Open Data Portal](https://dadosabertos.web.stj.jus.br/group/jurisprudencia), ensuring compliance with any terms of use, access policies, or data governance requirements enforced by the portal at the time of download.

This approach ensures that:
- Data is always fetched from the authoritative source.
- Users comply with the STJ Open Data Portal's current terms and policies.
- No court decision content is redistributed without authorization.

See `notebooks` for detailed instructions, required credentials (if any), and notes on how to reproduce the exact sample used in the paper (stratification criteria, date range, and semantic filtering parameters).

---

## Usage

### Running the baseline

_in progress_

### Running JAMEX

_in progress_

### Reproducing evaluation metrics

_in progress_

See the notebooks in `notebooks/` for step-by-step replication of all paper results.

---

## Research Questions

| RQ | Question |
|----|----------|
| **RQ1** | Does a multi-agent pipeline yield higher field-level extraction quality than a single strong prompt under IR-only context? |
| **RQ2** | Does agentic orchestration improve operational robustness without prohibitive efficiency penalties? |
| **RQ3** | Which extraction fields benefit most from agent specialization? |

**Hypotheses:** H0: µ(Base F1) ≥ µ(Agent F1) vs. H1: µ(Base F1) < µ(Agent F1)

---

## Results

> Full results are presented in the paper.

---

## Citation

If you use this code or dataset in your research, please cite:

_in progress_

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

The dataset derived from STJ public records is subject to the terms of the [STJ Open Data Portal](https://dadosabertos.web.stj.jus.br). Ground truth metadata was produced under institutional standards of the STJ indexing division and is provided here for research reproducibility only.

---

## Acknowledgements

This work is derived from a final project (*Trabalho de Conclusão de Curso*) of the Specialization in Data Science at **Pontifícia Universidade Católica do Paraná (PUCPR)**, where two of the authors are currently enrolled in the Master's program in Computer Science. We thank **PUCPR** for the academic environment and institutional support that made this work possible.

We gratefully acknowledge the **Superior Tribunal de Justiça (STJ)** for making their appellate decisions publicly available through the [Open Data Portal](https://dadosabertos.web.stj.jus.br/group/jurisprudencia), for the investment in infrastructure that made this research computationally feasible, and for the institutional support to scientific research.

We also thank the **Coordenação de Aperfeiçoamento de Pessoal de Nível Superior (CAPES)** for supporting scientific production and the development of the academic and technical faculty body in Brazil.
