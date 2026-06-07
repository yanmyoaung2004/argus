#!/usr/bin/env python3
"""CLI entry point to run evaluations, ablation studies, and generate reports.

Usage:
    # Run all benchmarks in mock mode (no external deps needed)
    python -m evaluation.runner benchmark

    # Run ablation study on the market research dataset
    python -m evaluation.runner ablation

    # Run a live benchmark (requires Redis + running Argus server)
    python -m evaluation.runner benchmark --mode live

    # Generate the report
    python -m evaluation.runner report

    # Run everything end-to-end
    python -m evaluation.runner all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evaluation.pipeline import run_benchmark

BASE_DIR = Path(__file__).parent
DATASETS_DIR = BASE_DIR / "datasets"
REPORTS_DIR = BASE_DIR / "reports"

DATASETS = [
    str(DATASETS_DIR / "market_research.json"),
    str(DATASETS_DIR / "tech_comparison.json"),
    str(DATASETS_DIR / "academic_survey.json"),
]


def cmd_benchmark(args: argparse.Namespace) -> int:
    datasets = args.datasets or DATASETS
    results: dict[str, object] = {}
    for path in datasets:
        print(f"\n=== Benchmark: {Path(path).stem} ===")
        result = run_benchmark(path, mode=args.mode)
        results[Path(path).stem] = result
        summary = result["summary"]
        print(f"  Entity F1:       {summary.get('avg_entity_f1', 0):.1%}")
        print(f"  Claim F1:        {summary.get('avg_claim_f1', 0):.1%}")
        print(f"  Hallucination:   {summary.get('avg_hallucination_rate', 0):.1%}")
        print(f"  Source Coverage: {summary.get('avg_source_coverage', 0):.1%}")
        print(f"  Calibration Err: {summary.get('avg_confidence_calibration_error', 0):.3f}")
        print(f"  Cost:            ${summary.get('avg_total_cost', 0):.4f}")
        print(f"  Time:            {summary.get('avg_research_time_seconds', 0):.1f}s")

    output_path = REPORTS_DIR / "benchmark_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nResults saved to {output_path}")
    return 0


def cmd_ablation(args: argparse.Namespace) -> int:
    dataset = args.dataset or DATASETS_DIR / "market_research.json"
    from evaluation.ablation import format_ablation_table, run_ablation

    print(f"\n=== Ablation Study: {Path(dataset).stem} ===")
    data = run_ablation(str(dataset), mode=args.mode)

    table = format_ablation_table(data)
    print(table)

    report_path = REPORTS_DIR / "ablation_results.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(table, encoding="utf-8")
    print(f"Report saved to {report_path}")

    json_path = REPORTS_DIR / "ablation_results.json"
    json_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return 0


def cmd_report(_args: argparse.Namespace) -> int:
    from evaluation.report import generate_report
    output = REPORTS_DIR / "phase5_results.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    generate_report(str(output))
    print(f"Report generated: {output}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    exit_code = 0
    print("=== Phase 5 Evaluation Suite ===\n")

    print("1. Benchmarking...")
    exit_code |= cmd_benchmark(args)

    print("\n2. Ablation Study...")
    exit_code |= cmd_ablation(args)

    print("\n3. Report Generation...")
    exit_code |= cmd_report(args)

    print("\n=== All evaluations complete ===")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Argus evaluation runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bench_parser = subparsers.add_parser("benchmark", help="Run benchmark on datasets")
    bench_parser.add_argument("--datasets", "-d", nargs="*", help="Dataset paths (default: all)")
    bench_parser.add_argument("--mode", "-m", choices=["mock", "live"], default="mock")

    abl_parser = subparsers.add_parser("ablation", help="Run ablation study")
    abl_parser.add_argument("--dataset", "-d", help="Dataset path (default: market_research)")
    abl_parser.add_argument("--mode", "-m", choices=["mock", "live"], default="mock")

    subparsers.add_parser("report", help="Generate evaluation report")

    all_parser = subparsers.add_parser("all", help="Run benchmarks + ablation + report")
    all_parser.add_argument("--mode", "-m", choices=["mock", "live"], default="mock")

    parsed = parser.parse_args()

    commands = {
        "benchmark": cmd_benchmark,
        "ablation": cmd_ablation,
        "report": cmd_report,
        "all": cmd_all,
    }

    return commands[parsed.command](parsed)


if __name__ == "__main__":
    sys.exit(main())
