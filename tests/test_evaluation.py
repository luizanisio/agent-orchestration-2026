"""Tests for src/evaluation/evaluator.py."""
import json
from unittest.mock import MagicMock

import pytest

from src.evaluation.evaluator import (
    EvaluationResult,
    FieldScore,
    LLMJudge,
    compute_metrics,
)
from src.schema import EspelhoMetadata


JUDGE_RESPONSE = {
    "field_scores": {
        "numero_processo": {"exact_match": 1.0, "fuzzy_score": 1.0, "present": 1.0},
        "classe": {"exact_match": 1.0, "fuzzy_score": 1.0, "present": 1.0},
        "relator": {"exact_match": 0.0, "fuzzy_score": 0.8, "present": 1.0},
        "ementa": {"exact_match": 0.0, "fuzzy_score": 0.9, "present": 1.0},
    },
    "overall_f1": 0.85,
    "precision": 0.90,
    "recall": 0.80,
    "judge_notes": ["Relator name differs slightly in formatting."],
}


def _mock_judge_client() -> MagicMock:
    client = MagicMock()
    client.complete.return_value = json.dumps(JUDGE_RESPONSE)
    return client


class TestEvaluationResult:
    def test_default_creation(self):
        er = EvaluationResult()
        assert er.overall_f1 == 0.0
        assert er.precision == 0.0
        assert er.recall == 0.0
        assert er.field_scores == {}
        assert er.judge_notes == []

    def test_creation_with_values(self):
        fs = {"numero_processo": FieldScore(exact_match=1.0, fuzzy_score=1.0, present=1.0)}
        er = EvaluationResult(
            field_scores=fs,
            overall_f1=0.9,
            precision=0.95,
            recall=0.85,
            judge_notes=["Good extraction."],
        )
        assert er.overall_f1 == 0.9
        assert er.field_scores["numero_processo"].exact_match == 1.0


class TestFieldScore:
    def test_defaults(self):
        fs = FieldScore()
        assert fs.exact_match == 0.0
        assert fs.fuzzy_score == 0.0
        assert fs.present == 0.0


class TestComputeMetrics:
    def test_empty_results(self):
        metrics = compute_metrics([])
        assert metrics["n"] == 0
        assert metrics["mean_f1"] == 0.0

    def test_single_result(self):
        er = EvaluationResult(overall_f1=0.8, precision=0.85, recall=0.75)
        metrics = compute_metrics([er])
        assert metrics["n"] == 1
        assert metrics["mean_f1"] == pytest.approx(0.8)
        assert metrics["mean_precision"] == pytest.approx(0.85)
        assert metrics["mean_recall"] == pytest.approx(0.75)

    def test_multiple_results(self):
        er1 = EvaluationResult(
            overall_f1=0.8,
            precision=0.9,
            recall=0.7,
            field_scores={"f1": FieldScore(exact_match=1.0, fuzzy_score=1.0, present=1.0)},
        )
        er2 = EvaluationResult(
            overall_f1=0.6,
            precision=0.7,
            recall=0.5,
            field_scores={"f1": FieldScore(exact_match=0.0, fuzzy_score=0.5, present=1.0)},
        )
        metrics = compute_metrics([er1, er2])
        assert metrics["n"] == 2
        assert metrics["mean_f1"] == pytest.approx(0.7)
        assert "f1" in metrics["per_field"]
        assert metrics["per_field"]["f1"]["mean_exact_match"] == pytest.approx(0.5)

    def test_per_field_averages(self):
        er1 = EvaluationResult(
            field_scores={"ementa": FieldScore(exact_match=1.0, fuzzy_score=0.9, present=1.0)}
        )
        er2 = EvaluationResult(
            field_scores={"ementa": FieldScore(exact_match=0.0, fuzzy_score=0.7, present=1.0)}
        )
        metrics = compute_metrics([er1, er2])
        ementa_metrics = metrics["per_field"]["ementa"]
        assert ementa_metrics["mean_exact_match"] == pytest.approx(0.5)
        assert ementa_metrics["mean_fuzzy_score"] == pytest.approx(0.8)
        assert ementa_metrics["count"] == 2


class TestLLMJudge:
    def test_evaluate_returns_evaluation_result(self):
        client = _mock_judge_client()
        judge = LLMJudge(client)
        extracted = EspelhoMetadata(numero_processo="REsp 1.234.567/SP")
        ground_truth = EspelhoMetadata(numero_processo="REsp 1.234.567/SP")
        result = judge.evaluate(extracted, ground_truth)
        assert isinstance(result, EvaluationResult)
        assert result.overall_f1 == pytest.approx(0.85)
        assert result.precision == pytest.approx(0.90)
        assert result.recall == pytest.approx(0.80)

    def test_evaluate_parses_field_scores(self):
        client = _mock_judge_client()
        judge = LLMJudge(client)
        result = judge.evaluate(EspelhoMetadata(), EspelhoMetadata())
        assert "numero_processo" in result.field_scores
        assert result.field_scores["numero_processo"].exact_match == 1.0

    def test_evaluate_includes_judge_notes(self):
        client = _mock_judge_client()
        judge = LLMJudge(client)
        result = judge.evaluate(EspelhoMetadata(), EspelhoMetadata())
        assert len(result.judge_notes) > 0

    def test_evaluate_handles_malformed_json(self):
        client = MagicMock()
        client.complete.return_value = "not valid json {"
        judge = LLMJudge(client)
        result = judge.evaluate(EspelhoMetadata(), EspelhoMetadata())
        assert isinstance(result, EvaluationResult)
        assert result.overall_f1 == 0.0
