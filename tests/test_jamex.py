"""Tests for the JAMEX pipeline (agents, memory, orchestrator)."""
import json
from unittest.mock import MagicMock

import pytest

from src.jamex.agents import (
    AgentContext,
    AgentOutput,
    ContentAgent,
    IdentificationAgent,
    LegislationAgent,
    PartyAgent,
    ProcedureAgent,
)
from src.jamex.memory import PipelineMemory
from src.jamex.orchestrator import JAMEXOrchestrator
from src.schema import ExtractionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(response_dict: dict) -> MagicMock:
    client = MagicMock()
    client.complete.return_value = json.dumps(response_dict)
    return client


IDENTIFICATION_RESPONSE = {
    "numero_registro": "2023/0001234-5",
    "numero_processo": "REsp 1.234.567/SP",
    "classe": "RECURSO ESPECIAL",
    "sigla_classe": "REsp",
    "tipo_recurso": "Recurso",
    "estado_origem": "SP",
}

PROCEDURE_RESPONSE = {
    "orgao_julgador": "TERCEIRA TURMA",
    "relator": "Ministro FULANO",
    "relator_designado": None,
    "data_julgamento": "01/03/2023",
    "data_publicacao": "15/03/2023",
    "resultado": "PROVIDO",
}

PARTY_RESPONSE = {
    "recorrente": "EMPRESA XYZ LTDA",
    "recorrido": "JOÃO DA SILVA",
}

CONTENT_RESPONSE = {
    "ementa": "Ementa completa do acórdão.",
    "assunto_principal": "Responsabilidade Civil",
    "tese_juridica": "Tese jurídica.",
}

LEGISLATION_RESPONSE = {
    "legislacao_aplicada": ["Art. 186 do CC"],
    "referencias_legislativas": ["CC/2002"],
    "palavras_chave": ["responsabilidade civil"],
}

PLAN_RESPONSE = {
    "present_sections": ["header", "parties", "ementa"],
    "complexity": "simple",
    "notes": ["Document is straightforward."],
    "priority_fields": ["numero_processo", "ementa"],
}

REVIEW_RESPONSE = {
    "approved": True,
    "corrections": {},
    "missing_fields": [],
    "quality_score": 0.95,
    "review_notes": ["Extraction looks complete."],
}


# ---------------------------------------------------------------------------
# AgentContext tests
# ---------------------------------------------------------------------------

class TestAgentContext:
    def test_creation_defaults(self):
        ctx = AgentContext(document_text="Test document.")
        assert ctx.document_text == "Test document."
        assert ctx.partial_results == {}
        assert ctx.agent_outputs == {}
        assert ctx.notes == []

    def test_updating_partial_results(self):
        ctx = AgentContext(document_text="Doc.")
        ctx.partial_results["numero_processo"] = "REsp 1.000.000/SP"
        assert ctx.partial_results["numero_processo"] == "REsp 1.000.000/SP"


# ---------------------------------------------------------------------------
# PipelineMemory tests
# ---------------------------------------------------------------------------

class TestPipelineMemory:
    def test_merge_fields_later_overrides_earlier(self):
        mem = PipelineMemory()
        out1 = AgentOutput(agent_name="A", fields={"f1": "v1", "f2": "v2"}, confidence=1.0)
        out2 = AgentOutput(agent_name="B", fields={"f2": "v2_updated", "f3": "v3"}, confidence=1.0)
        mem.add_agent_output(out1)
        mem.add_agent_output(out2)
        merged = mem.get_merged_fields()
        assert merged["f1"] == "v1"
        assert merged["f2"] == "v2_updated"
        assert merged["f3"] == "v3"

    def test_merge_ignores_none_values(self):
        mem = PipelineMemory()
        out1 = AgentOutput(agent_name="A", fields={"f1": "v1"}, confidence=1.0)
        out2 = AgentOutput(agent_name="B", fields={"f1": None}, confidence=0.5)
        mem.add_agent_output(out1)
        mem.add_agent_output(out2)
        merged = mem.get_merged_fields()
        assert merged["f1"] == "v1"

    def test_get_all_notes(self):
        mem = PipelineMemory()
        mem.planning_notes.append("plan note")
        mem.review_notes.append("review note")
        out = AgentOutput(agent_name="A", fields={}, confidence=1.0, notes=["agent note"])
        mem.add_agent_output(out)
        notes = mem.get_all_notes()
        assert "plan note" in notes
        assert "review note" in notes
        assert "agent note" in notes

    def test_to_context_summary_is_valid_json(self):
        mem = PipelineMemory()
        out = AgentOutput(agent_name="A", fields={"f": "v"}, confidence=1.0)
        mem.add_agent_output(out)
        summary = mem.to_context_summary()
        parsed = json.loads(summary)
        assert "merged_fields" in parsed
        assert parsed["merged_fields"]["f"] == "v"


# ---------------------------------------------------------------------------
# Individual agent tests
# ---------------------------------------------------------------------------

class TestIdentificationAgent:
    def test_extract_returns_agent_output(self):
        client = _mock_client(IDENTIFICATION_RESPONSE)
        agent = IdentificationAgent(client)
        ctx = AgentContext(document_text="Document text.")
        output = agent.extract(ctx)
        assert isinstance(output, AgentOutput)
        assert output.agent_name == "IdentificationAgent"
        assert output.fields["numero_processo"] == "REsp 1.234.567/SP"
        assert 0.0 <= output.confidence <= 1.0

    def test_extract_passes_partial_results_in_prompt(self):
        client = _mock_client(IDENTIFICATION_RESPONSE)
        agent = IdentificationAgent(client)
        ctx = AgentContext(document_text="Doc.", partial_results={"existing": "value"})
        agent.extract(ctx)
        call_args = client.complete.call_args[0][0]
        user_message = next(m["content"] for m in call_args if m["role"] == "user")
        assert "existing" in user_message


class TestProcedureAgent:
    def test_extract(self):
        client = _mock_client(PROCEDURE_RESPONSE)
        agent = ProcedureAgent(client)
        output = agent.extract(AgentContext(document_text="Doc."))
        assert output.fields["orgao_julgador"] == "TERCEIRA TURMA"
        assert output.fields["resultado"] == "PROVIDO"


class TestPartyAgent:
    def test_extract(self):
        client = _mock_client(PARTY_RESPONSE)
        agent = PartyAgent(client)
        output = agent.extract(AgentContext(document_text="Doc."))
        assert output.fields["recorrente"] == "EMPRESA XYZ LTDA"
        assert output.fields["recorrido"] == "JOÃO DA SILVA"


class TestContentAgent:
    def test_extract(self):
        client = _mock_client(CONTENT_RESPONSE)
        agent = ContentAgent(client)
        output = agent.extract(AgentContext(document_text="Doc."))
        assert output.fields["ementa"] == "Ementa completa do acórdão."


class TestLegislationAgent:
    def test_extract_returns_lists(self):
        client = _mock_client(LEGISLATION_RESPONSE)
        agent = LegislationAgent(client)
        output = agent.extract(AgentContext(document_text="Doc."))
        assert isinstance(output.fields["legislacao_aplicada"], list)
        assert isinstance(output.fields["palavras_chave"], list)

    def test_extract_none_becomes_empty_list(self):
        client = _mock_client({"legislacao_aplicada": None, "referencias_legislativas": None, "palavras_chave": None})
        agent = LegislationAgent(client)
        output = agent.extract(AgentContext(document_text="Doc."))
        assert output.fields["legislacao_aplicada"] == []


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------

def _make_orchestrator_client() -> MagicMock:
    """Return a mock client that returns appropriate responses for each agent."""
    responses = [
        PLAN_RESPONSE,
        IDENTIFICATION_RESPONSE,
        PROCEDURE_RESPONSE,
        PARTY_RESPONSE,
        CONTENT_RESPONSE,
        LEGISLATION_RESPONSE,
        REVIEW_RESPONSE,
    ]
    call_count = {"n": 0}

    def side_effect(messages, **kwargs):
        idx = call_count["n"] % len(responses)
        call_count["n"] += 1
        return json.dumps(responses[idx])

    client = MagicMock()
    client.complete.side_effect = side_effect
    return client


class TestJAMEXOrchestrator:
    def test_full_pipeline_returns_extraction_result(self):
        client = _make_orchestrator_client()
        orchestrator = JAMEXOrchestrator(
            agent_client=client,
            enable_planning=True,
            enable_review=True,
            enable_memory=True,
        )
        result = orchestrator.extract("Full court decision text here.")
        assert isinstance(result, ExtractionResult)
        assert result.metadata is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_pipeline_without_planning_and_review(self):
        responses = [
            IDENTIFICATION_RESPONSE,
            PROCEDURE_RESPONSE,
            PARTY_RESPONSE,
            CONTENT_RESPONSE,
            LEGISLATION_RESPONSE,
        ]
        call_count = {"n": 0}

        def side_effect(messages, **kwargs):
            idx = call_count["n"] % len(responses)
            call_count["n"] += 1
            return json.dumps(responses[idx])

        client = MagicMock()
        client.complete.side_effect = side_effect

        orchestrator = JAMEXOrchestrator(
            agent_client=client,
            enable_planning=False,
            enable_review=False,
            enable_memory=True,
        )
        result = orchestrator.extract("Court decision text.")
        assert isinstance(result, ExtractionResult)
        # Exactly 5 agent calls, no planning or review
        assert client.complete.call_count == 5

    def test_pipeline_merges_fields_from_all_agents(self):
        # Use agent-only responses (no planning/review calls)
        agent_responses = [
            IDENTIFICATION_RESPONSE,
            PROCEDURE_RESPONSE,
            PARTY_RESPONSE,
            CONTENT_RESPONSE,
            LEGISLATION_RESPONSE,
        ]
        call_count = {"n": 0}

        def side_effect(messages, **kwargs):
            idx = call_count["n"] % len(agent_responses)
            call_count["n"] += 1
            return json.dumps(agent_responses[idx])

        client = MagicMock()
        client.complete.side_effect = side_effect
        orchestrator = JAMEXOrchestrator(
            agent_client=client,
            enable_planning=False,
            enable_review=False,
        )
        result = orchestrator.extract("Document.")
        # Fields from IdentificationAgent
        assert result.metadata.numero_processo == "REsp 1.234.567/SP"
        # Fields from ProcedureAgent
        assert result.metadata.relator == "Ministro FULANO"
        # Fields from PartyAgent
        assert result.metadata.recorrente == "EMPRESA XYZ LTDA"
        # Fields from ContentAgent
        assert result.metadata.ementa == "Ementa completa do acórdão."
