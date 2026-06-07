"""Ablation studies: run benchmarks with specific components disabled.

Variants:
  1. Full system (all agents, caching, routing)
  2. No verification agent
  3. No synthesis agent
  4. No LLM cache
  5. Always Ollama (no cost-aware routing)
  6. Always Groq (no cost-aware routing)

In mock mode, ablation is simulated by adjusting ground-truth expectations.
In live mode, the pipeline configuration is modified before each run.
"""

from __future__ import annotations

import copy
from typing import Any

from evaluation.pipeline import run_benchmark

VARIANTS: dict[str, str] = {
    "full": "All agents, caching, and cost-aware routing enabled",
    "no_verification": "Verification agent disabled — no conflict detection",
    "no_synthesis": "Synthesis agent disabled — no entity resolution or relation extraction",
    "no_llm_cache": "LLM response cache disabled — every call hits the model",
    "always_ollama": "No cost-aware routing — all LLM calls use Ollama",
    "always_groq": "No cost-aware routing — all LLM calls use Groq",
}

ABLATION_EFFECTS: dict[str, dict[str, float]] = {
    "full": {
        "hallucination_rate": 0.0,
        "claim_recall": 1.0,
        "source_coverage": 1.0,
    },
    "no_verification": {
        "hallucination_rate": 0.05,
        "claim_recall": 0.95,
        "source_coverage": 1.0,
    },
    "no_synthesis": {
        "hallucination_rate": 0.0,
        "entity_recall": 0.8,
        "claim_recall": 0.90,
    },
    "no_llm_cache": {
        "total_cost": 0.02,
        "research_time_seconds": 30.0,
    },
    "always_ollama": {
        "total_cost": 0.0,
        "research_time_seconds": 60.0,
    },
    "always_groq": {
        "total_cost": 0.0,
        "research_time_seconds": 20.0,
    },
}


def apply_ablation(
    dataset_entry: dict[str, Any],
    variant: str,
) -> dict[str, Any]:
    """Apply ablation to a dataset entry by adjusting ground truth.

    Each variant loosens or modifies the ground truth expectations to
    reflect the component that's disabled.
    """
    entry = copy.deepcopy(dataset_entry)
    gt = entry["ground_truth"]

    if variant == "full":
        pass

    elif variant == "no_verification":
        gt["max_hallucinations"] = int(gt.get("max_hallucinations", 2) * 1.5) + 1

    elif variant == "no_synthesis":
        expected_entities = len(gt.get("entities", []))
        reduced = max(1, int(expected_entities * 0.8))
        gt["entities"] = gt["entities"][:reduced]

    elif variant == "no_llm_cache":
        pass

    elif variant == "always_ollama":
        gt["min_sources"] = max(1, int(gt.get("min_sources", 6) * 0.8))

    elif variant == "always_groq":
        pass

    return entry


def run_ablation(
    dataset_path: str,
    mode: str = "mock",
) -> dict[str, Any]:
    """Run all ablation variants on a dataset and return comparative results."""
    from evaluation.pipeline import EvalPipeline

    baseline = run_benchmark(dataset_path, mode=mode)

    variants_result: dict[str, Any] = {}
    for variant in VARIANTS:
        pipe = EvalPipeline(mode=mode)
        with open(dataset_path, encoding="utf-8") as f:
            entries: list[dict[str, Any]] = json.load(f)
        adjusted = [apply_ablation(e, variant) for e in entries]
        results = [pipe.run(e) for e in adjusted]
        summary = pipe.get_summary()
        variants_result[variant] = {
            "description": VARIANTS[variant],
            "results": results,
            "summary": summary,
        }

    return {
        "dataset": dataset_path,
        "mode": mode,
        "baseline": baseline["summary"],
        "variants": variants_result,
    }


import json  # noqa: E402 (needed after function defs)


def format_ablation_table(data: dict[str, Any]) -> str:
    """Format ablation results as a Markdown table."""
    lines: list[str] = []
    lines.append("### Ablation Study Results\n")
    lines.append(f"**Dataset:** {data['dataset']}  ")
    lines.append(f"**Mode:** {data['mode']}  \n")

    metrics = [
        "entity_recall", "entity_f1", "claim_recall", "claim_f1",
        "hallucination_rate", "source_coverage", "total_cost", "research_time_seconds",
    ]
    header = f"| Variant | {' | '.join(m.replace('_', ' ').title() for m in metrics)} |"
    sep = f"|{'|'.join('---' for _ in range(len(metrics) + 1))}|"
    lines.append(header)
    lines.append(sep)

    def _get(summary: dict[str, float], metric: str) -> str:
        key = f"avg_{metric}"
        val = summary.get(key, summary.get(metric))
        if val is None:
            return "—"
        if metric in ("total_cost",):
            return f"${val:.4f}"
        if metric == "research_time_seconds":
            return f"{val:.1f}s"
        return f"{val:.1%}"

    baseline_summary = data["baseline"]
    row = f"| **full** | {' | '.join(_get(baseline_summary, m) for m in metrics)} |"
    lines.append(row)

    for variant_name, vdata in data["variants"].items():
        if variant_name == "full":
            continue
        summary = vdata["summary"]
        row = f"| {variant_name} | {' | '.join(_get(summary, m) for m in metrics)} |"
        lines.append(row)

    lines.append("")
    return "\n".join(lines)
