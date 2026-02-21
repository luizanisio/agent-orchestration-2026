"""JAMEX orchestrator: plans, executes, reviews, and merges agent outputs."""
import json
from typing import Optional

from src.llm_client import LLMClient
from src.schema import EspelhoMetadata, ExtractionResult, validate_metadata
from src.jamex.agents import (
    AgentContext,
    ContentAgent,
    IdentificationAgent,
    LegislationAgent,
    PartyAgent,
    ProcedureAgent,
)
from src.jamex.memory import PipelineMemory

PLANNING_PROMPT = """You are the planning agent for a judicial metadata extraction pipeline.
Given a Brazilian STJ court decision, analyze it and produce an execution plan.
Identify which metadata fields are likely present and note any special considerations.
Return a JSON with:
- present_sections: list of sections you can identify (e.g., "header", "parties", "ementa", "legislation")
- complexity: "simple" | "moderate" | "complex"
- notes: list of specific observations for downstream agents
- priority_fields: list of the most critical fields to extract"""

REVIEW_PROMPT = """You are the review agent for a judicial metadata extraction pipeline.
Review the extracted metadata for completeness, consistency, and accuracy.
Return a JSON with:
- approved: boolean - whether extraction meets quality standards
- corrections: dict of field -> corrected_value for any corrections needed
- missing_fields: list of fields that appear to be in the document but were not extracted
- quality_score: float 0.0-1.0
- review_notes: list of observations"""


class JAMEXOrchestrator:
    """Orchestrates the full JAMEX multi-agent extraction pipeline."""

    def __init__(
        self,
        agent_client: LLMClient,
        review_client: Optional[LLMClient] = None,
        enable_planning: bool = True,
        enable_review: bool = True,
        enable_memory: bool = True,
        max_review_iterations: int = 1,
    ):
        self.agent_client = agent_client
        # Fall back to agent_client if no separate review client provided
        self.review_client = review_client or agent_client
        self.enable_planning = enable_planning
        self.enable_review = enable_review
        self.enable_memory = enable_memory
        self.max_review_iterations = max_review_iterations

        # Instantiate specialist agents
        self._agents = [
            IdentificationAgent(agent_client),
            ProcedureAgent(agent_client),
            PartyAgent(agent_client),
            ContentAgent(agent_client),
            LegislationAgent(agent_client),
        ]

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _run_planning(self, document_text: str, memory: PipelineMemory) -> dict:
        """Call the planning agent and store its notes in memory."""
        messages = [
            {"role": "system", "content": PLANNING_PROMPT},
            {
                "role": "user",
                "content": f"Analyze this court decision and produce an extraction plan:\n\n{document_text}",
            },
        ]
        raw = self.review_client.complete(messages, response_format={"type": "json_object"})
        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            plan = {}

        notes: list[str] = plan.get("notes", [])
        if isinstance(notes, list):
            memory.planning_notes.extend(notes)
        return plan

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def _run_review(
        self,
        document_text: str,
        merged_fields: dict,
        memory: PipelineMemory,
    ) -> dict:
        """Call the review agent and apply any corrections to merged_fields."""
        messages = [
            {"role": "system", "content": REVIEW_PROMPT},
            {
                "role": "user",
                "content": (
                    "Review the following extracted metadata against the original document.\n\n"
                    "Original document:\n"
                    + document_text
                    + "\n\nExtracted metadata:\n"
                    + json.dumps(merged_fields, ensure_ascii=False, indent=2)
                ),
            },
        ]
        raw = self.review_client.complete(messages, response_format={"type": "json_object"})
        try:
            review = json.loads(raw)
        except json.JSONDecodeError:
            review = {}

        review_notes: list[str] = review.get("review_notes", [])
        if isinstance(review_notes, list):
            memory.review_notes.extend(review_notes)

        # Apply corrections
        corrections: dict = review.get("corrections", {}) or {}
        for field_name, corrected_value in corrections.items():
            if corrected_value is not None:
                merged_fields[field_name] = corrected_value

        return review

    # ------------------------------------------------------------------
    # Main extraction
    # ------------------------------------------------------------------

    def extract(self, document_text: str) -> ExtractionResult:
        """Run the full JAMEX pipeline on a document."""
        memory = PipelineMemory() if self.enable_memory else PipelineMemory()

        # 1. Planning phase
        if self.enable_planning:
            self._run_planning(document_text, memory)

        # 2. Execution phase — run agents sequentially, passing partial results
        context = AgentContext(document_text=document_text)
        for agent in self._agents:
            output = agent.extract(context)
            # Update shared context with newly extracted fields
            for k, v in output.fields.items():
                if v is not None:
                    context.partial_results[k] = v
            context.agent_outputs[output.agent_name] = output.fields
            if self.enable_memory:
                memory.add_agent_output(output)

        # 3. Merge all agent outputs
        merged = memory.get_merged_fields() if self.enable_memory else context.partial_results

        # 4. Review phase (with optional re-extraction iteration)
        for _iteration in range(self.max_review_iterations if self.enable_review else 0):
            memory.iterations += 1
            self._run_review(document_text, merged, memory)

        # 5. Build final metadata
        valid_keys = EspelhoMetadata.model_fields.keys()
        metadata = EspelhoMetadata(**{k: v for k, v in merged.items() if k in valid_keys})

        validation = validate_metadata(metadata)
        total_fields = len(EspelhoMetadata.model_fields)
        present_fields = sum(1 for v in merged.values() if v is not None)
        confidence = present_fields / total_fields

        all_notes = memory.get_all_notes() + validation.validation_notes

        return ExtractionResult(
            metadata=metadata,
            confidence=confidence,
            extraction_notes=all_notes,
        )
