# JAMEX: Judicial Multi-Agent Metadata Extraction

**Agent Orchestration — LLM-powered legal metadata extraction from Brazilian STJ court decisions**

## Overview

JAMEX (Judicial Multi-Agent Metadata Extraction) is a research pipeline that extracts structured metadata from Brazilian Superior Tribunal de Justiça (STJ) court decisions (*Espelhos de Acórdão*) using a multi-agent LLM architecture.

The pipeline decomposes metadata extraction into specialist agents, each responsible for a focused subset of fields, coordinated by a central orchestrator with optional planning and review phases.

## Architecture

```
Document Text
     │
     ▼
┌─────────────┐
│  Planner    │  (optional) — analyzes document structure
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  Specialist Agents (sequential, dependency- │
│  aware context passing)                     │
│                                             │
│  1. IdentificationAgent  — case IDs         │
│  2. ProcedureAgent       — judgment info    │
│  3. PartyAgent           — parties          │
│  4. ContentAgent         — ementa, thesis   │
│  5. LegislationAgent     — laws, keywords   │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│  Reviewer   │  (optional) — quality check + corrections
└──────┬──────┘
       │
       ▼
 EspelhoMetadata  (Pydantic model)
```

## Project Structure

```
.
├── requirements.txt
├── src/
│   ├── schema.py              # Pydantic metadata schema + validation
│   ├── llm_client.py          # Unified OpenAI/Ollama LLM client
│   ├── baseline/
│   │   └── extractor.py       # Single-prompt baseline extractor
│   ├── jamex/
│   │   ├── agents.py          # Specialist agent implementations
│   │   ├── memory.py          # Pipeline memory / traceability
│   │   └── orchestrator.py    # JAMEX orchestrator
│   └── evaluation/
│       └── evaluator.py       # LLM-as-a-Judge evaluator
├── data/
│   └── download_dataset.py    # STJ Open Data Portal downloader
└── tests/
    ├── test_schema.py
    ├── test_baseline.py
    ├── test_jamex.py
    └── test_evaluation.py
```

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

### Using the JAMEX pipeline

```python
from src.llm_client import get_client_from_env, ReasoningEffort
from src.jamex.orchestrator import JAMEXOrchestrator

client = get_client_from_env("gpt-4o-mini", reasoning_effort=ReasoningEffort.LOW)

orchestrator = JAMEXOrchestrator(
    agent_client=client,
    enable_planning=True,
    enable_review=True,
)

with open("data/raw/decision.txt") as f:
    document_text = f.read()

result = orchestrator.extract(document_text)
print(result.metadata.model_dump_json(indent=2))
print(f"Confidence: {result.confidence:.2%}")
```

### Using the baseline extractor

```python
from src.llm_client import get_client_from_env
from src.baseline.extractor import BaselineExtractor

client = get_client_from_env("gpt-4o-mini")
extractor = BaselineExtractor(client)
result = extractor.extract(document_text)
```

### Evaluating extractions

```python
from src.llm_client import get_client_from_env, ReasoningEffort
from src.evaluation.evaluator import LLMJudge, compute_metrics

judge_client = get_client_from_env("gpt-4o", reasoning_effort=ReasoningEffort.MEDIUM)
judge = LLMJudge(judge_client)

eval_result = judge.evaluate(extracted=result.metadata, ground_truth=ground_truth_metadata)
print(f"F1: {eval_result.overall_f1:.3f}")
```

### Downloading the dataset

```bash
python data/download_dataset.py \
  --output-dir data/raw \
  --start-date 2023-01-01 \
  --end-date 2024-12-31 \
  --max-documents 1225
```

## Configuration

Set these environment variables:

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_BASE_URL` | Custom base URL (for Azure, local proxies, etc.) |

For Ollama (local models):

```python
from src.llm_client import LLMClient, ModelProvider

client = LLMClient(
    model="gemma3:12b",
    provider=ModelProvider.OLLAMA,
    base_url="http://localhost:11434/v1",
)
```

## Running Tests

```bash
pytest tests/ -v
```

## Metadata Schema

The `EspelhoMetadata` Pydantic model captures:

| Field | Description |
|---|---|
| `numero_registro` | Registration number |
| `numero_processo` | Process number (e.g., "REsp 1.234.567/SP") |
| `classe` | Case class (e.g., "RECURSO ESPECIAL") |
| `orgao_julgador` | Judging body |
| `relator` | Rapporteur name |
| `data_julgamento` | Judgment date (DD/MM/YYYY) |
| `data_publicacao` | Publication date (DD/MM/YYYY) |
| `resultado` | Outcome (e.g., "PROVIDO") |
| `ementa` | Full summary text |
| `tese_juridica` | Legal thesis |
| `legislacao_aplicada` | Applied legislation (list) |
| `palavras_chave` | Keywords (list) |
| `recorrente` / `recorrido` | Appellant / Appellee |
| `estado_origem` | Origin state (UF) |

## License

See [LICENSE](LICENSE).
