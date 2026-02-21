"""LLM-as-a-Judge evaluator for metadata extraction quality."""
import json
from dataclasses import dataclass, field
from typing import Optional

from src.llm_client import LLMClient, ReasoningEffort
from src.schema import EspelhoMetadata

JUDGE_SYSTEM_PROMPT = """You are an expert judge evaluating the quality of metadata extracted from Brazilian STJ court decisions.
Compare the extracted metadata against the ground truth and provide field-level accuracy scores.

For each field, assess:
- exact_match: whether the extracted value exactly matches ground truth (1.0 or 0.0)
- fuzzy_score: semantic similarity score (0.0-1.0) for text fields
- present: whether the field was extracted (1.0 or 0.0)

Return a JSON with:
- field_scores: dict of field_name -> {exact_match: float, fuzzy_score: float, present: float}
- overall_f1: overall F1 score across all fields
- precision: precision score
- recall: recall score
- judge_notes: list of specific observations"""


@dataclass
class FieldScore:
    exact_match: float = 0.0
    fuzzy_score: float = 0.0
    present: float = 0.0


@dataclass
class EvaluationResult:
    field_scores: dict[str, FieldScore] = field(default_factory=dict)
    overall_f1: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    judge_notes: list[str] = field(default_factory=list)


class LLMJudge:
    """LLM-as-a-Judge evaluator using medium reasoning effort."""

    def __init__(self, client: LLMClient):
        self.client = client

    def evaluate(
        self,
        extracted: EspelhoMetadata,
        ground_truth: EspelhoMetadata,
    ) -> EvaluationResult:
        """Evaluate extraction quality against ground truth."""
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Evaluate the extracted metadata against the ground truth.\n\n"
                    "Ground truth:\n"
                    + json.dumps(ground_truth.model_dump(), ensure_ascii=False, indent=2)
                    + "\n\nExtracted:\n"
                    + json.dumps(extracted.model_dump(), ensure_ascii=False, indent=2)
                ),
            },
        ]
        raw = self.client.complete(messages, response_format={"type": "json_object"})
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        field_scores: dict[str, FieldScore] = {}
        raw_scores = data.get("field_scores", {})
        if isinstance(raw_scores, dict):
            for fname, scores in raw_scores.items():
                if isinstance(scores, dict):
                    field_scores[fname] = FieldScore(
                        exact_match=float(scores.get("exact_match", 0.0)),
                        fuzzy_score=float(scores.get("fuzzy_score", 0.0)),
                        present=float(scores.get("present", 0.0)),
                    )

        return EvaluationResult(
            field_scores=field_scores,
            overall_f1=float(data.get("overall_f1", 0.0)),
            precision=float(data.get("precision", 0.0)),
            recall=float(data.get("recall", 0.0)),
            judge_notes=data.get("judge_notes", []) if isinstance(data.get("judge_notes"), list) else [],
        )


def compute_metrics(results: list[EvaluationResult]) -> dict:
    """Compute aggregate metrics across multiple evaluation results."""
    if not results:
        return {
            "mean_f1": 0.0,
            "mean_precision": 0.0,
            "mean_recall": 0.0,
            "per_field": {},
            "n": 0,
        }

    n = len(results)
    mean_f1 = sum(r.overall_f1 for r in results) / n
    mean_precision = sum(r.precision for r in results) / n
    mean_recall = sum(r.recall for r in results) / n

    # Collect all field names
    all_fields: set[str] = set()
    for r in results:
        all_fields.update(r.field_scores.keys())

    per_field: dict[str, dict] = {}
    for fname in all_fields:
        scores = [r.field_scores[fname] for r in results if fname in r.field_scores]
        if scores:
            per_field[fname] = {
                "mean_exact_match": sum(s.exact_match for s in scores) / len(scores),
                "mean_fuzzy_score": sum(s.fuzzy_score for s in scores) / len(scores),
                "mean_present": sum(s.present for s in scores) / len(scores),
                "count": len(scores),
            }

    return {
        "mean_f1": mean_f1,
        "mean_precision": mean_precision,
        "mean_recall": mean_recall,
        "per_field": per_field,
        "n": n,
    }
