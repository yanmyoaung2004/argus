from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

API_BASE = "http://localhost:8000"


def _sse_events(url: str) -> Any:
    """Yield parsed SSE events from a streaming response."""
    with httpx.stream("GET", url, timeout=None) as resp:
        for line in resp.iter_lines():
            line = line.strip()
            if line.startswith("data: "):
                yield json.loads(line[6:])


def run_research(args: argparse.Namespace) -> None:
    query = args.query
    max_sources = args.max_sources
    time_limit = args.time_limit

    print(f"  Submitting research: {query[:80]}{'...' if len(query) > 80 else ''}")
    print(f"    max sources: {max_sources}  ·  time limit: {time_limit} min")
    print()

    # Submit
    try:
        resp = httpx.post(
            f"{API_BASE}/research",
            json={
                "query": query,
                "max_sources": max_sources,
                "max_duration_minutes": time_limit,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        return
    except httpx.RequestError as exc:
        print(f"  ❌ Cannot reach Argus server at {API_BASE}")
        print("     Make sure `python -m argus` is running.")
        print(f"     Error: {exc}")
        sys.exit(1)

    data: dict[str, Any] = resp.json()
    task_id = str(data["task_id"])
    print(f"  🆔 Task ID: {task_id}")
    print()

    # Watch SSE
    print("  Watching progress...")
    print()
    sse_url = f"{API_BASE}/research/{task_id}/status"
    done = False
    failed = False

    try:
        for event in _sse_events(sse_url):
            event_type = event.get("type", "")
            msg = event.get("message", "")
            if event_type == "progress" and msg:
                agent = event.get("agent", "")
                label = f"[{agent}] " if agent else ""
                print(f"    {label}{msg}")
            elif event_type == "step_complete":
                print(f"    ✅ Step {event.get('step_id')} complete")
            elif event_type == "step_failed":
                print(f"    ❌ Step {event.get('step_id')} failed: {msg}")
            elif event_type == "research_complete":
                print("\n  ✅ Research complete!")
                done = True
                break
            elif event_type == "research_failed":
                print(f"\n  ❌ Research failed: {msg}")
                failed = True
                break
    except KeyboardInterrupt:
        print("\n  Cancelled. Report may still be available.")
        return

    if not done and not failed:
        print("  ⏳ Research still running — fetching report anyway...")

    # Fetch HTML report
    print()
    print("  Fetching report...")
    try:
        resp = httpx.get(f"{API_BASE}/research/{task_id}/html", timeout=30)
        if resp.status_code != 200:
            print(f"  ❌ Report not ready yet (HTTP {resp.status_code})")
            print(f"     Try: curl {API_BASE}/research/{task_id}/html")
            return
    except httpx.RequestError as exc:
        print(f"  ❌ Failed to fetch report: {exc}")
        return

    # Save
    slug = "".join(
        c if c.isalnum() or c in " -_" else "" for c in query
    )[:40].strip().replace(" ", "_")
    out_path = Path(f"report_{slug}_{task_id[:8]}.html")
    out_path.write_text(resp.text, "utf-8")
    print(f"  📄 Report saved to {out_path}")

    # Open in browser
    import webbrowser
    webbrowser.open(str(out_path.absolute()))
    print("  🌐 Opening in browser")


def add_subparser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "research", help="Submit a research query and get an HTML report"
    )
    parser.add_argument("query", help="Research topic or question")
    parser.add_argument(
        "--max-sources", "-s",
        type=int,
        default=50,
        help="Maximum sources to collect (default: 50, max: 500)",
    )
    parser.add_argument(
        "--time-limit", "-t",
        type=int,
        default=30,
        help="Maximum research time in minutes (default: 30, max: 360)",
    )
    parser.set_defaults(func=run_research)
