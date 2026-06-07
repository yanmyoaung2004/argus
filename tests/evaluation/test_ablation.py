from __future__ import annotations

from evaluation.ablation import VARIANTS, apply_ablation


class TestAblationApply:
    def test_full_does_not_modify(self) -> None:
        entry = {"query": "test", "ground_truth": {"entities": ["A"], "max_hallucinations": 2}}
        modified = apply_ablation(entry, "full")
        assert modified["ground_truth"]["max_hallucinations"] == 2
        assert modified["ground_truth"]["entities"] == ["A"]

    def test_no_verification_loosens_hallucinations(self) -> None:
        entry = {"query": "test", "ground_truth": {"max_hallucinations": 2}}
        modified = apply_ablation(entry, "no_verification")
        assert modified["ground_truth"]["max_hallucinations"] > 2

    def test_no_synthesis_reduces_entities(self) -> None:
        entry = {"query": "test", "ground_truth": {"entities": ["A", "B", "C", "D", "E"]}}
        modified = apply_ablation(entry, "no_synthesis")
        assert len(modified["ground_truth"]["entities"]) < 5

    def test_no_llm_cache_passes_through(self) -> None:
        entry = {"query": "test", "ground_truth": {"entities": ["A"]}}
        modified = apply_ablation(entry, "no_llm_cache")
        assert modified["ground_truth"]["entities"] == ["A"]

    def test_always_ollama_reduces_sources(self) -> None:
        entry = {"query": "test", "ground_truth": {"min_sources": 10}}
        modified = apply_ablation(entry, "always_ollama")
        assert modified["ground_truth"]["min_sources"] < 10

    def test_always_groq_passes_through(self) -> None:
        entry = {"query": "test", "ground_truth": {"entities": ["A"]}}
        modified = apply_ablation(entry, "always_groq")
        assert modified["ground_truth"]["entities"] == ["A"]

    def test_all_variants_defined(self) -> None:
        assert len(VARIANTS) == 6
        assert "full" in VARIANTS
        assert "no_verification" in VARIANTS
        assert "no_synthesis" in VARIANTS
        assert "no_llm_cache" in VARIANTS
        assert "always_ollama" in VARIANTS
        assert "always_groq" in VARIANTS
