"""Memory management for JAMEX pipeline."""
import json
from dataclasses import dataclass, field
from typing import Any

from src.jamex.agents import AgentOutput


@dataclass
class PipelineMemory:
    """Stores intermediate agent outputs and decisions for traceability."""

    agent_outputs: list[AgentOutput] = field(default_factory=list)
    planning_notes: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)
    iterations: int = 0

    def add_agent_output(self, output: AgentOutput) -> None:
        """Append an agent output to the memory."""
        self.agent_outputs.append(output)

    def get_merged_fields(self) -> dict[str, Any]:
        """Merge all agent outputs; later agents override earlier ones for non-None values."""
        merged: dict[str, Any] = {}
        for output in self.agent_outputs:
            for k, v in output.fields.items():
                if v is not None:
                    merged[k] = v
        return merged

    def to_context_summary(self) -> str:
        """Return a JSON string summary of completed work."""
        summary = {
            "iterations": self.iterations,
            "agents_run": [o.agent_name for o in self.agent_outputs],
            "merged_fields": self.get_merged_fields(),
            "planning_notes": self.planning_notes,
            "review_notes": self.review_notes,
        }
        return json.dumps(summary, ensure_ascii=False, indent=2)

    def get_all_notes(self) -> list[str]:
        """Collect notes from all stages."""
        return (
            self.planning_notes
            + self.review_notes
            + [n for o in self.agent_outputs for n in o.notes]
        )
