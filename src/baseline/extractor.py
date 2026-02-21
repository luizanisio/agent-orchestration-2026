"""Baseline single-prompt metadata extractor for Espelho do Acórdão."""
import json

from src.llm_client import LLMClient
from src.schema import EspelhoMetadata, ExtractionResult, validate_metadata

EXTRACTION_PROMPT = """You are an expert legal metadata extractor for Brazilian STJ court decisions.
Extract ALL available metadata from the provided court decision text (Espelho do Acórdão).

Return a JSON object with the following fields (use null for fields not found):
- numero_registro: registration number
- numero_processo: process number (e.g., "REsp 1.234.567/SP")
- classe: case class (e.g., "RECURSO ESPECIAL")
- orgao_julgador: judging body (e.g., "TERCEIRA TURMA")
- relator: rapporteur full name
- relator_designado: designated rapporteur if different from original
- data_julgamento: judgment date in DD/MM/YYYY format
- data_publicacao: publication date in DD/MM/YYYY format
- sigla_classe: class abbreviation (e.g., "REsp")
- tipo_recurso: resource type
- resultado: outcome (e.g., "PROVIDO", "NÃO PROVIDO", "PARCIALMENTE PROVIDO")
- ementa: full summary text exactly as written
- tese_juridica: legal thesis statement
- legislacao_aplicada: list of applied legislation (list of strings)
- palavras_chave: list of keywords (list of strings)
- assunto_principal: main legal subject
- referencias_legislativas: list of legislative references (list of strings)
- recorrente: appellant name
- recorrido: appellee name
- estado_origem: origin state abbreviation (e.g., "SP", "RJ")

Extract accurately and completely. Do not invent information not present in the text."""


class BaselineExtractor:
    """Single-prompt baseline extractor."""

    def __init__(self, client: LLMClient):
        self.client = client

    def extract(self, document_text: str) -> ExtractionResult:
        """Extract metadata from a court decision document in a single LLM call."""
        messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"Extract metadata from this court decision:\n\n{document_text}",
            },
        ]
        response = self.client.complete(messages, response_format={"type": "json_object"})
        data = json.loads(response)

        valid_keys = EspelhoMetadata.model_fields.keys()
        metadata = EspelhoMetadata(**{k: v for k, v in data.items() if k in valid_keys})

        validation = validate_metadata(metadata)
        total_required = len(validation.missing_required) + (
            len(
                [
                    f
                    for f in ["numero_processo", "classe", "relator", "data_julgamento", "ementa", "resultado"]
                    if getattr(metadata, f, None) is not None
                ]
            )
        )
        confidence = 1.0 - (len(validation.missing_required) / max(total_required, 1))

        return ExtractionResult(
            metadata=metadata,
            confidence=confidence,
            extraction_notes=validation.validation_notes,
        )
