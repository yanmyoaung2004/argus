from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx

API_BASE = "http://localhost:8000"


def run_list(args: argparse.Namespace) -> None:  # noqa: ARG001
    try:
        resp = httpx.get(f"{API_BASE}/research", timeout=15)
        resp.raise_for_status()
    except httpx.RequestError as exc:
        print(f"  ❌ Cannot reach Argus server at {API_BASE}")
        print("     Make sure `python -m argus` is running.")
        print(f"     Error: {exc}")
        sys.exit(1)

    tasks: list[dict[str, Any]] = resp.json()

    if not tasks:
        print("  No research tasks found.")
        return

    print(f"  {'Task ID':<40} {'Status':<20} {'Query':<50} {'Cost':<10}")
    print(f"  {'─'*40} {'─'*20} {'─'*50} {'─'*10}")
    for t in tasks:
        tid = str(t["task_id"])[:36]
        status = t["status"]
        query = t["query"][:47] + "..." if len(t["query"]) > 50 else t["query"]
        cost = f"${t['total_cost']:.4f}"
        print(f"  {tid:<40} {status:<20} {query:<50} {cost:<10}")


def run_status(args: argparse.Namespace) -> None:
    task_id = args.task_id

    try:
        resp = httpx.get(f"{API_BASE}/research/{task_id}", timeout=15)
        if resp.status_code == 404:
            print(f"  ❌ Task '{task_id}' not found.")
            sys.exit(1)
        resp.raise_for_status()
    except httpx.RequestError as exc:
        print(f"  ❌ Cannot reach Argus server at {API_BASE}")
        print("     Make sure `python -m argus` is running.")
        print(f"     Error: {exc}")
        sys.exit(1)

    t: dict[str, Any] = resp.json()

    print(f"  Task ID:     {t['task_id']}")
    print(f"  Query:       {t['query']}")
    print(f"  Status:      {t['status']}")
    print(f"  Max sources: {t.get('max_sources', '—')}")
    print(f"  Max time:    {t.get('max_duration_minutes', '—')} min")
    print(f"  Created:     {t.get('created_at', '—')}")
    print(f"  Completed:   {t.get('completed_at', '—')}")
    print(f"  Cost:        ${t.get('total_cost', 0):.4f}")
    if t.get("error_message"):
        print(f"  Error:       {t['error_message']}")
    plan = t.get("plan")
    if plan and plan.get("steps"):
        print()
        print(f"  Steps ({len(plan['steps'])}):")
        for s in plan["steps"]:
            status_icon = "✅" if s.get("status") == "completed" else "⏳"
            print(f"    {status_icon} [{s.get('agent', '?')}] {s.get('goal', '?')}")


def add_subparser(subparsers: Any) -> None:
    parser = subparsers.add_parser("list", help="List all research tasks")
    parser.set_defaults(func=run_list)

    parser = subparsers.add_parser("status", help="Show research task status")
    parser.add_argument("task_id", help="Task ID (UUID)")
    parser.set_defaults(func=run_status)
