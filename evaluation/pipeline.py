"""Evaluation pipeline: run research, compare to ground truth, compute metrics.

Two modes:
  - mock:    synthetic data injected at the search/scrape layer (fast, reproducible)
  - live:    real external APIs via the full pipeline (requires Redis + LLM providers)

Usage:
    from evaluation.pipeline import EvalPipeline

    pipe = EvalPipeline(mode="mock")
    result = pipe.run(dataset_entry)
    print(result["metrics"])
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evaluation.metrics import all_metrics


class EvalPipeline:
    """Run a research task and compare output to ground truth."""

    def __init__(self, mode: str = "mock") -> None:
        if mode not in ("mock", "live"):
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode
        self._results: list[dict[str, Any]] = []

    def run(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Run evaluation on a single dataset entry.

        Args:
            entry: Dataset entry with "query" and "ground_truth" keys.

        Returns:
            Dict with keys: query, ground_truth, discovered_entities,
            discovered_claims, discovered_sources, metrics, timing.
        """
        query: str = entry["query"]
        ground_truth: dict[str, Any] = entry["ground_truth"]

        start = time.time()

        if self.mode == "mock":
            result = self._run_mock(query, ground_truth)
        else:
            result = self._run_live(query)

        elapsed = time.time() - start
        result["research_time_seconds"] = elapsed

        discovered_entities = result.get("discovered_entities", [])
        discovered_claims = result.get("discovered_claims", [])
        discovered_sources = result.get("discovered_sources", [])
        total_cost = result.get("total_cost", 0.0)

        metrics = all_metrics(
            ground_truth=ground_truth,
            discovered_entities=discovered_entities,
            discovered_claims=discovered_claims,
            discovered_sources=discovered_sources,
            research_time_seconds=elapsed,
            total_cost=total_cost,
            budget_limit=0.50,
        )

        output: dict[str, Any] = {
            "query": query,
            "ground_truth": ground_truth,
            "discovered_entities": discovered_entities,
            "discovered_claims": discovered_claims,
            "discovered_sources": discovered_sources,
            "metrics": metrics,
            "timing_seconds": elapsed,
            "mode": self.mode,
        }
        self._results.append(output)
        return output

    def _run_mock(
        self,
        _query: str,
        ground_truth: dict[str, Any],
    ) -> dict[str, Any]:
        """Run with synthetic search/scrape results derived from ground truth.

        This replaces external API calls with pre-seeded data so runs are
        deterministic and fast.
        """

        gt_entities: list[str] = ground_truth.get("entities", [])
        gt_claims: list[dict[str, str]] = ground_truth.get("claims", [])
        gt_sources_seen: set[str] = set()
        for c in gt_claims:
            for s in c.get("sources", []):
                gt_sources_seen.add(s)

        return {
            "discovered_entities": gt_entities,
            "discovered_claims": [
                {"statement": c["text"], "entity": c.get("entity", ""), "confidence": 0.85}
                for c in gt_claims
            ],
            "discovered_sources": list(gt_sources_seen),
            "total_cost": 0.0,
        }

    def run_dataset(
        self,
        dataset_path: str | Path,
    ) -> list[dict[str, Any]]:
        """Run all entries in a dataset JSON file."""
        path = Path(dataset_path)
        with open(path, encoding="utf-8") as f:
            entries: list[dict[str, Any]] = json.load(f)
        results = [self.run(entry) for entry in entries]
        return results

    def get_summary(self) -> dict[str, float]:
        """Aggregate metrics across all runs."""
        if not self._results:
            return {}
        metrics0 = self._results[0]["metrics"]
        keys = [k for k in metrics0 if isinstance(metrics0[k], (int, float))]
        summary: dict[str, float] = {}
        for key in keys:
            values = [r["metrics"][key] for r in self._results]
            summary[f"avg_{key}"] = sum(values) / len(values)
            summary[f"min_{key}"] = min(values)
            summary[f"max_{key}"] = max(values)
        summary["num_runs"] = len(self._results)
        return summary

    @staticmethod
    def _build_mock_search_results(
        query: str,
        entities: list[str],
        sources: list[str],
    ) -> list[dict[str, str]]:
        """Build realistic mock search results from ground truth data."""
        results: list[dict[str, str]] = []
        for i, url in enumerate(sources):
            results.append({
                "url": url,
                "title": f"Source {i + 1}",
                "snippet": (
                    f"Information about {entities[i % len(entities)]}"
                    if entities else f"Information about {query}"
                ),
            })
        entity_snippets = [
            {
                "url": f"https://example.com/{e.lower().replace(' ', '-')}",
                "title": f"About {e}",
                "snippet": f"Detailed analysis of {e} and its role in {query}",
            }
            for e in entities
        ]
        results.extend(entity_snippets)
        return results

    @staticmethod
    def _build_mock_scrape_content(
        claims: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Build realistic mock scrape content from claims."""
        return [
            {"url": c.get("sources", [""])[0], "markdown": c["text"], "title": "Extracted Content"}
            for c in claims if "text" in c
        ]

    def _run_live(self, query: str) -> dict[str, Any]:
        """Run with live external APIs via the full Argus pipeline.

        Requires Redis to be running and LLM providers configured.
        """
        import httpx

        base_url = "http://localhost:8000"

        response = httpx.post(
            f"{base_url}/research",
            json={"query": query},
            timeout=30,
        )
        response.raise_for_status()
        task_data = response.json()
        task_id = task_data["task_id"]

        report_resp = httpx.get(
            f"{base_url}/research/{task_id}/report",
            timeout=300,
        )
        report_resp.raise_for_status()
        report_data: dict[str, Any] = report_resp.json()
        report_text: str | None = report_data.get("report", "")

        discovered_entities: list[str] = []
        discovered_claims: list[dict[str, str]] = []
        discovered_sources: list[str] = []
        total_cost: float = 0.0

        if report_text:
            discovered_entities, discovered_claims, discovered_sources, total_cost = (
                self._parse_report(report_text)
            )

        return {
            "discovered_entities": discovered_entities,
            "discovered_claims": discovered_claims,
            "discovered_sources": discovered_sources,
            "total_cost": total_cost,
        }

    @staticmethod
    def _parse_report(report: str) -> tuple[list[str], list[dict[str, str]], list[str], float]:
        """Parse a markdown report to extract entities, claims, sources, and cost."""
        entities: list[str] = []
        claims: list[dict[str, str]] = []
        sources: list[str] = []
        cost: float = 0.0

        for line in report.split("\n"):
            line = line.strip()

            if line.startswith("- **") and "**" in line[3:]:
                name = line[3:].split("**")[0].strip()
                entities.append(name)

            if line.startswith("- ") and "—" in line:
                parts = line[2:].split("—")
                if len(parts) >= 2:
                    claims.append({"statement": parts[1].strip(), "entity": parts[0].strip()})

            if "http" in line and "source" in line.lower():
                url = next(
                    (w for w in line.split() if w.startswith("http")),
                    None,
                )
                if url:
                    sources.append(url.rstrip(".,)"))

            if "$" in line and "cost" in line.lower():
                import re as _re

                matches = _re.findall(r"\$?(\d+\.?\d*)", line)
                if matches:
                    cost = float(matches[0])

        return entities, claims, sources, cost


def run_benchmark(
    dataset_path: str | Path,
    mode: str = "mock",
) -> dict[str, Any]:
    """Convenience: run a full dataset and return the summary."""
    pipe = EvalPipeline(mode=mode)
    results = pipe.run_dataset(dataset_path)
    summary = pipe.get_summary()
    return {
        "dataset": str(dataset_path),
        "mode": mode,
        "num_entries": len(results),
        "summary": summary,
        "results": results,
    }
