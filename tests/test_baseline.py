"""Tests for src/baseline/extractor.py."""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.baseline.extractor import BaselineExtractor
from src.schema import EspelhoMetadata, ExtractionResult


FULL_RESPONSE = {
    "numero_registro": "2023/0001234-5",
    "numero_processo": "REsp 1.234.567/SP",
    "classe": "RECURSO ESPECIAL",
    "orgao_julgador": "TERCEIRA TURMA",
    "relator": "Ministro FULANO DE TAL",
    "relator_designado": None,
    "data_julgamento": "01/03/2023",
    "data_publicacao": "15/03/2023",
    "sigla_classe": "REsp",
    "tipo_recurso": "Recurso",
    "resultado": "PROVIDO",
    "ementa": "Ementa do acórdão para fins de teste.",
    "tese_juridica": "Tese jurídica aqui.",
    "legislacao_aplicada": ["Art. 186 do CC"],
    "palavras_chave": ["responsabilidade civil"],
    "assunto_principal": "Responsabilidade Civil",
    "referencias_legislativas": ["CC/2002"],
    "recorrente": "EMPRESA XYZ LTDA",
    "recorrido": "JOÃO DA SILVA",
    "estado_origem": "SP",
}

PARTIAL_RESPONSE = {
    "numero_processo": "HC 123.456/RJ",
    "classe": "HABEAS CORPUS",
    "relator": "Ministra BELTRANA",
    "data_julgamento": "05/05/2024",
    "ementa": "Ementa parcial.",
    "resultado": "NÃO PROVIDO",
}


def _mock_client(response_dict: dict) -> MagicMock:
    client = MagicMock()
    client.complete.return_value = json.dumps(response_dict)
    return client


class TestBaselineExtractor:
    def test_successful_extraction(self):
        client = _mock_client(FULL_RESPONSE)
        extractor = BaselineExtractor(client)
        result = extractor.extract("Documento de teste.")

        assert isinstance(result, ExtractionResult)
        assert result.metadata.numero_processo == "REsp 1.234.567/SP"
        assert result.metadata.classe == "RECURSO ESPECIAL"
        assert result.metadata.relator == "Ministro FULANO DE TAL"
        assert result.metadata.resultado == "PROVIDO"
        assert result.confidence > 0.0

    def test_extraction_with_partial_data(self):
        client = _mock_client(PARTIAL_RESPONSE)
        extractor = BaselineExtractor(client)
        result = extractor.extract("Documento parcial.")

        assert isinstance(result, ExtractionResult)
        assert result.metadata.numero_processo == "HC 123.456/RJ"
        assert result.metadata.orgao_julgador is None
        assert result.metadata.recorrente is None
        # Some required fields are present, some not
        assert result.confidence >= 0.0

    def test_extraction_result_structure(self):
        client = _mock_client(FULL_RESPONSE)
        extractor = BaselineExtractor(client)
        result = extractor.extract("Test document.")

        assert hasattr(result, "metadata")
        assert hasattr(result, "confidence")
        assert hasattr(result, "extraction_notes")
        assert isinstance(result.extraction_notes, list)
        assert 0.0 <= result.confidence <= 1.0

    def test_llm_called_with_messages(self):
        client = _mock_client(FULL_RESPONSE)
        extractor = BaselineExtractor(client)
        extractor.extract("My document text.")

        client.complete.assert_called_once()
        call_args = client.complete.call_args
        messages = call_args[0][0]
        assert any("system" == m["role"] for m in messages)
        assert any("user" == m["role"] for m in messages)

    def test_extra_keys_in_response_ignored(self):
        """Unknown keys in LLM response should not cause errors."""
        response_with_extra = {**PARTIAL_RESPONSE, "unknown_field": "some value"}
        client = _mock_client(response_with_extra)
        extractor = BaselineExtractor(client)
        result = extractor.extract("Document.")
        assert isinstance(result, ExtractionResult)
