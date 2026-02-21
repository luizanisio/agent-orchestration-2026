"""Schema definitions for Brazilian STJ court decision metadata (Espelho do Acórdão)."""
from typing import Optional
from pydantic import BaseModel

REQUIRED_FIELDS = [
    "numero_processo",
    "classe",
    "relator",
    "data_julgamento",
    "ementa",
    "resultado",
]


class EspelhoMetadata(BaseModel):
    """Metadata schema for a Brazilian STJ court decision."""

    numero_registro: Optional[str] = None
    numero_processo: Optional[str] = None
    classe: Optional[str] = None
    orgao_julgador: Optional[str] = None
    relator: Optional[str] = None
    relator_designado: Optional[str] = None
    data_julgamento: Optional[str] = None
    data_publicacao: Optional[str] = None
    sigla_classe: Optional[str] = None
    tipo_recurso: Optional[str] = None
    resultado: Optional[str] = None
    ementa: Optional[str] = None
    tese_juridica: Optional[str] = None
    legislacao_aplicada: Optional[list[str]] = None
    palavras_chave: Optional[list[str]] = None
    assunto_principal: Optional[str] = None
    referencias_legislativas: Optional[list[str]] = None
    recorrente: Optional[str] = None
    recorrido: Optional[str] = None
    estado_origem: Optional[str] = None


class ExtractionResult(BaseModel):
    """Result of a metadata extraction attempt."""

    metadata: EspelhoMetadata
    confidence: float
    extraction_notes: list[str] = []


class ValidationResult(BaseModel):
    """Result of metadata validation."""

    is_valid: bool
    missing_required: list[str]
    validation_notes: list[str]


def validate_metadata(metadata: EspelhoMetadata) -> ValidationResult:
    """Check if required fields are present and non-None."""
    missing = [f for f in REQUIRED_FIELDS if getattr(metadata, f, None) is None]
    notes: list[str] = []
    if missing:
        notes.append(f"Missing required fields: {', '.join(missing)}")
    return ValidationResult(
        is_valid=len(missing) == 0,
        missing_required=missing,
        validation_notes=notes,
    )
