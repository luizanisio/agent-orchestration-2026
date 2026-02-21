"""Specialist agents for JAMEX pipeline."""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from src.llm_client import LLMClient


@dataclass
class AgentContext:
    """Shared context passed between agents."""

    document_text: str
    partial_results: dict[str, Any] = field(default_factory=dict)
    agent_outputs: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class AgentOutput:
    """Output from a single agent."""

    agent_name: str
    fields: dict[str, Any]
    confidence: float
    notes: list[str] = field(default_factory=list)
    raw_response: str = ""


class BaseAgent(ABC):
    """Abstract base class for all specialist agents."""

    def __init__(self, client: LLMClient):
        self.client = client

    @abstractmethod
    def extract(self, context: AgentContext) -> AgentOutput:
        """Extract fields from the document using the provided context."""

    def _call_llm(self, messages: list[dict]) -> dict:
        """Call the LLM and parse the JSON response."""
        raw = self.client.complete(messages, response_format={"type": "json_object"})
        try:
            return json.loads(raw), raw
        except json.JSONDecodeError:
            return {}, raw

    def _partial_context_snippet(self, context: AgentContext) -> str:
        """Return a compact JSON representation of already-extracted fields."""
        if not context.partial_results:
            return ""
        return (
            "\n\nFields already extracted by previous agents (for context):\n"
            + json.dumps(context.partial_results, ensure_ascii=False, indent=2)
        )


# ---------------------------------------------------------------------------
# Specialist agents
# ---------------------------------------------------------------------------

class IdentificationAgent(BaseAgent):
    """Extracts case identification fields."""

    SYSTEM_PROMPT = """You are a specialist in extracting case identification information from Brazilian STJ court decisions.

Extract ONLY the following fields (use null for fields not found):
- numero_registro: registration number (e.g., "2023/0123456-7")
- numero_processo: process number (e.g., "REsp 1.234.567/SP")
- classe: case class in full (e.g., "RECURSO ESPECIAL")
- sigla_classe: class abbreviation (e.g., "REsp", "AREsp", "HC")
- tipo_recurso: resource type (e.g., "Recurso", "Habeas Corpus")
- estado_origem: origin state abbreviation (e.g., "SP", "RJ", "MG")

Return a JSON object with exactly these keys."""

    def extract(self, context: AgentContext) -> AgentOutput:
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract identification metadata from this court decision:"
                    + self._partial_context_snippet(context)
                    + f"\n\nDocument:\n{context.document_text}"
                ),
            },
        ]
        data, raw = self._call_llm(messages)
        target_keys = {"numero_registro", "numero_processo", "classe", "sigla_classe", "tipo_recurso", "estado_origem"}
        fields = {k: v for k, v in data.items() if k in target_keys}
        confidence = sum(1 for v in fields.values() if v is not None) / len(target_keys)
        return AgentOutput(
            agent_name="IdentificationAgent",
            fields=fields,
            confidence=confidence,
            raw_response=raw,
        )


class ProcedureAgent(BaseAgent):
    """Extracts procedural and judgment fields."""

    SYSTEM_PROMPT = """You are a specialist in extracting procedural and judgment information from Brazilian STJ court decisions.

Extract ONLY the following fields (use null for fields not found):
- orgao_julgador: judging body (e.g., "TERCEIRA TURMA", "PRIMEIRA SEÇÃO")
- relator: rapporteur full name (e.g., "Ministro JOÃO DA SILVA")
- relator_designado: designated rapporteur if different from the original relator (null if same)
- data_julgamento: judgment date in DD/MM/YYYY format
- data_publicacao: publication date in DD/MM/YYYY format
- resultado: outcome (e.g., "PROVIDO", "NÃO PROVIDO", "PARCIALMENTE PROVIDO", "PREJUDICADO")

Return a JSON object with exactly these keys."""

    def extract(self, context: AgentContext) -> AgentOutput:
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract procedural metadata from this court decision:"
                    + self._partial_context_snippet(context)
                    + f"\n\nDocument:\n{context.document_text}"
                ),
            },
        ]
        data, raw = self._call_llm(messages)
        target_keys = {"orgao_julgador", "relator", "relator_designado", "data_julgamento", "data_publicacao", "resultado"}
        fields = {k: v for k, v in data.items() if k in target_keys}
        confidence = sum(1 for v in fields.values() if v is not None) / len(target_keys)
        return AgentOutput(
            agent_name="ProcedureAgent",
            fields=fields,
            confidence=confidence,
            raw_response=raw,
        )


class PartyAgent(BaseAgent):
    """Extracts party information."""

    SYSTEM_PROMPT = """You are a specialist in identifying parties in Brazilian STJ court decisions.

Extract ONLY the following fields (use null for fields not found):
- recorrente: appellant name(s) — the party who filed the appeal
- recorrido: appellee name(s) — the responding party

Return a JSON object with exactly these keys."""

    def extract(self, context: AgentContext) -> AgentOutput:
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract party information from this court decision:"
                    + self._partial_context_snippet(context)
                    + f"\n\nDocument:\n{context.document_text}"
                ),
            },
        ]
        data, raw = self._call_llm(messages)
        target_keys = {"recorrente", "recorrido"}
        fields = {k: v for k, v in data.items() if k in target_keys}
        confidence = sum(1 for v in fields.values() if v is not None) / len(target_keys)
        return AgentOutput(
            agent_name="PartyAgent",
            fields=fields,
            confidence=confidence,
            raw_response=raw,
        )


class ContentAgent(BaseAgent):
    """Extracts substantive content fields."""

    SYSTEM_PROMPT = """You are a specialist in extracting substantive legal content from Brazilian STJ court decisions.

Extract ONLY the following fields (use null for fields not found):
- ementa: the full ementa (summary) text, copied exactly as it appears in the document
- assunto_principal: the main legal subject or topic
- tese_juridica: the legal thesis or ratio decidendi established in the decision

Return a JSON object with exactly these keys."""

    def extract(self, context: AgentContext) -> AgentOutput:
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract substantive content from this court decision:"
                    + self._partial_context_snippet(context)
                    + f"\n\nDocument:\n{context.document_text}"
                ),
            },
        ]
        data, raw = self._call_llm(messages)
        target_keys = {"ementa", "assunto_principal", "tese_juridica"}
        fields = {k: v for k, v in data.items() if k in target_keys}
        confidence = sum(1 for v in fields.values() if v is not None) / len(target_keys)
        return AgentOutput(
            agent_name="ContentAgent",
            fields=fields,
            confidence=confidence,
            raw_response=raw,
        )


class LegislationAgent(BaseAgent):
    """Extracts legislation and keyword fields."""

    SYSTEM_PROMPT = """You are a specialist in extracting legislative references and keywords from Brazilian STJ court decisions.

Extract ONLY the following fields (use empty list [] for fields not found):
- legislacao_aplicada: list of legislation articles directly applied in the decision (e.g., ["Art. 186 do Código Civil", "Art. 927 do CC/2002"])
- referencias_legislativas: list of all legislative references mentioned (broader than legislacao_aplicada)
- palavras_chave: list of relevant legal keywords and topics

Return a JSON object with exactly these keys. Values must be lists of strings."""

    def extract(self, context: AgentContext) -> AgentOutput:
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract legislation and keywords from this court decision:"
                    + self._partial_context_snippet(context)
                    + f"\n\nDocument:\n{context.document_text}"
                ),
            },
        ]
        data, raw = self._call_llm(messages)
        target_keys = {"legislacao_aplicada", "referencias_legislativas", "palavras_chave"}
        fields = {k: v for k, v in data.items() if k in target_keys}
        # Ensure list fields are actually lists
        for key in target_keys:
            if fields.get(key) is None:
                fields[key] = []
            elif not isinstance(fields[key], list):
                fields[key] = [str(fields[key])]
        confidence = sum(1 for v in fields.values() if v) / len(target_keys)
        return AgentOutput(
            agent_name="LegislationAgent",
            fields=fields,
            confidence=confidence,
            raw_response=raw,
        )
