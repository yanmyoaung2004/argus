from __future__ import annotations

from evaluation.metrics import (
    all_metrics,
    claim_precision,
    claim_recall,
    confidence_calibration_error,
    entity_precision,
    entity_recall,
    f1_score,
    hallucination_rate,
    source_coverage,
    source_precision,
)


class TestEntityRecall:
    def test_all_found(self) -> None:
        gt = ["OpenAI", "Anthropic", "Google"]
        found = ["OpenAI", "Anthropic", "Google"]
        assert entity_recall(gt, found) == 1.0

    def test_partial_found(self) -> None:
        gt = ["OpenAI", "Anthropic", "Google"]
        found = ["OpenAI"]
        assert entity_recall(gt, found) == 1.0 / 3.0

    def test_none_found(self) -> None:
        gt = ["OpenAI", "Anthropic"]
        found: list[str] = []
        assert entity_recall(gt, found) == 0.0

    def test_empty_ground_truth(self) -> None:
        assert entity_recall([], ["OpenAI"]) == 1.0

    def test_case_insensitive(self) -> None:
        gt = ["openai"]
        found = ["OpenAI"]
        assert entity_recall(gt, found) == 1.0


class TestEntityPrecision:
    def test_all_correct(self) -> None:
        gt = ["OpenAI", "Anthropic"]
        found = ["OpenAI", "Anthropic"]
        assert entity_precision(gt, found) == 1.0

    def test_partial_correct(self) -> None:
        gt = ["OpenAI"]
        found = ["OpenAI", "HallucinatedCo"]
        assert entity_precision(gt, found) == 0.5

    def test_empty_found(self) -> None:
        assert entity_precision(["OpenAI"], []) == 0.0

    def test_none_correct(self) -> None:
        gt = ["OpenAI"]
        found = ["FakeCorp"]
        assert entity_precision(gt, found) == 0.0


class TestClaimRecall:
    def test_all_found(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}, {"text": "Anthropic valued at $5B"}]
        found = [
            {"statement": "OpenAI was valued at $10 billion"},
            {"statement": "Anthropic was valued at $5 billion"},
        ]
        recall = claim_recall(gt, found)
        assert recall >= 0.99

    def test_partial(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}, {"text": "Anthropic valued at $5B"}]
        found = [{"statement": "OpenAI was valued at $10 billion"}]
        recall = claim_recall(gt, found)
        assert recall == 0.5

    def test_empty_found(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}]
        assert claim_recall(gt, []) == 0.0

    def test_empty_ground_truth(self) -> None:
        assert claim_recall([], [{"statement": "test"}]) == 1.0


class TestClaimPrecision:
    def test_all_correct(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}]
        found = [{"statement": "OpenAI valued at $10B"}]
        assert claim_precision(gt, found) == 1.0

    def test_some_hallucinated(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}]
        found = [
            {"statement": "OpenAI valued at $10B"},
            {"statement": "FakeCo acquired for $1T"},
        ]
        assert claim_precision(gt, found) == 0.5

    def test_empty_found(self) -> None:
        assert claim_precision([{"text": "test"}], []) == 1.0

    def test_no_match(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}]
        found = [{"statement": "Totally unrelated fact"}]
        prec = claim_precision(gt, found)
        assert prec < 0.1


class TestHallucinationRate:
    def test_no_hallucinations(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}]
        found = [{"statement": "OpenAI valued at $10B"}]
        assert hallucination_rate(gt, found) == 0.0

    def test_all_hallucinated(self) -> None:
        gt = [{"text": "OpenAI valued at $10B"}]
        found = [{"statement": "FakeCo acquired for $1T"}]
        assert hallucination_rate(gt, found) >= 0.9


class TestSourceCoverage:
    def test_all_found(self) -> None:
        gt = ["https://example.com/a", "https://example.com/b"]
        found = ["https://example.com/a", "https://example.com/b"]
        assert source_coverage(gt, found) == 1.0

    def test_partial(self) -> None:
        gt = ["https://example.com/a", "https://example.com/b"]
        found = ["https://example.com/a"]
        assert source_coverage(gt, found) == 0.5

    def test_empty_found(self) -> None:
        assert source_coverage(["https://example.com/a"], []) == 0.0

    def test_trailing_slash(self) -> None:
        gt = ["https://example.com/a"]
        found = ["https://example.com/a/"]
        assert source_coverage(gt, found) == 1.0

    def test_case_insensitive(self) -> None:
        gt = ["https://EXAMPLE.COM/A"]
        found = ["https://example.com/a"]
        assert source_coverage(gt, found) == 1.0


class TestSourcePrecision:
    def test_all_correct(self) -> None:
        gt = ["https://example.com/a"]
        found = ["https://example.com/a"]
        assert source_precision(gt, found) == 1.0

    def test_some_extra(self) -> None:
        gt = ["https://example.com/a"]
        found = ["https://example.com/a", "https://example.com/b"]
        assert source_precision(gt, found) == 0.5

    def test_empty_found(self) -> None:
        assert source_precision(["https://example.com/a"], []) == 1.0


class TestConfidenceCalibrationError:
    def test_perfect_calibration(self) -> None:
        claims = [
            {"statement": "OpenAI valued at $10B", "confidence": 1.0},
            {"statement": "FakeCo acquired for $1T", "confidence": 0.0},
        ]
        gt_texts = {"OpenAI valued at $10B"}
        error = confidence_calibration_error(claims, gt_texts)
        assert error == 0.0

    def test_imperfect_calibration(self) -> None:
        claims = [
            {"statement": "OpenAI valued at $10B", "confidence": 0.0},
        ]
        gt_texts = {"OpenAI valued at $10B"}
        error = confidence_calibration_error(claims, gt_texts)
        assert error == 1.0

    def test_empty_claims(self) -> None:
        assert confidence_calibration_error([], {"test"}) == 0.0

    def test_default_confidence(self) -> None:
        claims = [
            {"statement": "OpenAI valued at $10B"},
        ]
        gt_texts = {"OpenAI valued at $10B"}
        error = confidence_calibration_error(claims, gt_texts)
        assert 0.0 <= error <= 1.0


class TestF1Score:
    def test_perfect(self) -> None:
        assert f1_score(1.0, 1.0) == 1.0

    def test_zero_precision(self) -> None:
        assert f1_score(0.0, 1.0) == 0.0

    def test_zero_recall(self) -> None:
        assert f1_score(1.0, 0.0) == 0.0

    def test_mid_range(self) -> None:
        assert f1_score(0.5, 0.5) == 0.5

    def test_harmonic_penalty(self) -> None:
        score = f1_score(1.0, 0.5)
        assert 0.0 < score < 1.0
        assert score < 0.75


class TestAllMetrics:
    def test_returns_all_keys(self) -> None:
        gt = {
            "entities": ["OpenAI"],
            "claims": [{"text": "OpenAI valued at $10B", "sources": ["https://example.com"]}],
        }
        metrics = all_metrics(gt, ["OpenAI"], [{"statement": "OpenAI valued at $10B"}], ["https://example.com"])
        assert "entity_recall" in metrics
        assert "claim_recall" in metrics
        assert "hallucination_rate" in metrics
        assert "source_coverage" in metrics
        assert "confidence_calibration_error" in metrics
        assert "total_cost" in metrics
        assert "research_time_seconds" in metrics

    def test_perfect_match(self) -> None:
        gt = {
            "entities": ["OpenAI", "Anthropic"],
            "claims": [
                {"text": "OpenAI valued at $10B", "sources": ["https://example.com/a"]},
                {"text": "Anthropic valued at $5B", "sources": ["https://example.com/b"]},
            ],
        }
        metrics = all_metrics(
            gt,
            ["OpenAI", "Anthropic"],
            [
                {"statement": "OpenAI valued at $10B"},
                {"statement": "Anthropic valued at $5B"},
            ],
            ["https://example.com/a", "https://example.com/b"],
        )
        assert metrics["entity_recall"] == 1.0
        assert metrics["entity_precision"] == 1.0
        assert metrics["entity_f1"] == 1.0
        assert metrics["claim_recall"] >= 0.99
        assert metrics["claim_precision"] >= 0.99
        assert metrics["hallucination_rate"] <= 0.01
        assert metrics["source_coverage"] == 1.0

    def test_empty_discovered(self) -> None:
        gt = {
            "entities": ["OpenAI"],
            "claims": [{"text": "OpenAI valued at $10B", "sources": ["https://example.com"]}],
        }
        metrics = all_metrics(gt, [], [], [])
        assert metrics["entity_recall"] == 0.0
        assert metrics["claim_recall"] == 0.0
        assert metrics["source_coverage"] == 0.0

    def test_cost_vs_budget(self) -> None:
        gt = {"entities": [], "claims": []}
        metrics = all_metrics(gt, [], [], [], total_cost=0.25, budget_limit=0.50)
        assert metrics["cost_vs_budget"] == 0.5
