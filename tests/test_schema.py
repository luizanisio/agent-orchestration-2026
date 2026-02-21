"""Tests for src/schema.py."""
import pytest
from src.schema import (
    REQUIRED_FIELDS,
    EspelhoMetadata,
    ExtractionResult,
    ValidationResult,
    validate_metadata,
)


class TestEspelhoMetadata:
    def test_creation_with_all_fields(self):
        m = EspelhoMetadata(
            numero_registro="2023/0001234-5",
            numero_processo="REsp 1.234.567/SP",
            classe="RECURSO ESPECIAL",
            orgao_julgador="TERCEIRA TURMA",
            relator="Ministro FULANO DE TAL",
            relator_designado=None,
            data_julgamento="01/03/2023",
            data_publicacao="15/03/2023",
            sigla_classe="REsp",
            tipo_recurso="Recurso",
            resultado="PROVIDO",
            ementa="Ementa do acórdão.",
            tese_juridica="Tese jurídica.",
            legislacao_aplicada=["Art. 186 do CC"],
            palavras_chave=["responsabilidade civil"],
            assunto_principal="Responsabilidade Civil",
            referencias_legislativas=["CC/2002"],
            recorrente="EMPRESA XYZ LTDA",
            recorrido="JOÃO DA SILVA",
            estado_origem="SP",
        )
        assert m.numero_processo == "REsp 1.234.567/SP"
        assert m.classe == "RECURSO ESPECIAL"
        assert m.legislacao_aplicada == ["Art. 186 do CC"]

    def test_creation_with_none_fields(self):
        m = EspelhoMetadata()
        for fname in EspelhoMetadata.model_fields:
            assert getattr(m, fname) is None

    def test_partial_creation(self):
        m = EspelhoMetadata(numero_processo="HC 123.456/RJ")
        assert m.numero_processo == "HC 123.456/RJ"
        assert m.relator is None


class TestValidateMetadata:
    def test_missing_required_fields(self):
        m = EspelhoMetadata()
        result = validate_metadata(m)
        assert result.is_valid is False
        assert set(result.missing_required) == set(REQUIRED_FIELDS)
        assert len(result.validation_notes) > 0

    def test_all_required_fields_present(self):
        m = EspelhoMetadata(
            numero_processo="REsp 1.000.000/SP",
            classe="RECURSO ESPECIAL",
            relator="Ministro FULANO",
            data_julgamento="01/01/2024",
            ementa="Texto da ementa.",
            resultado="PROVIDO",
        )
        result = validate_metadata(m)
        assert result.is_valid is True
        assert result.missing_required == []

    def test_partial_required_fields(self):
        m = EspelhoMetadata(numero_processo="REsp 1.000.000/SP", classe="RECURSO ESPECIAL")
        result = validate_metadata(m)
        assert result.is_valid is False
        assert "relator" in result.missing_required
        assert "ementa" in result.missing_required


class TestExtractionResult:
    def test_creation(self):
        metadata = EspelhoMetadata(numero_processo="REsp 1.000.000/SP")
        result = ExtractionResult(metadata=metadata, confidence=0.8)
        assert result.confidence == 0.8
        assert result.extraction_notes == []

    def test_creation_with_notes(self):
        metadata = EspelhoMetadata()
        result = ExtractionResult(
            metadata=metadata, confidence=0.3, extraction_notes=["note1", "note2"]
        )
        assert result.extraction_notes == ["note1", "note2"]


class TestValidationResult:
    def test_creation_valid(self):
        vr = ValidationResult(is_valid=True, missing_required=[], validation_notes=[])
        assert vr.is_valid is True

    def test_creation_invalid(self):
        vr = ValidationResult(
            is_valid=False,
            missing_required=["relator", "ementa"],
            validation_notes=["Missing required fields: relator, ementa"],
        )
        assert vr.is_valid is False
        assert "relator" in vr.missing_required
