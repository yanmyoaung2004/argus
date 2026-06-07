from __future__ import annotations

import argparse
import json
import sys

import httpx


def _parse_sse_line(line: str) -> tuple[str, str] | None:
    if not line or not line.startswith("event:") and not line.startswith("data:"):
        return None
    if line.startswith("event:"):
        return ("event", line[6:].strip())
    if line.startswith("data:"):
        return ("data", line[5:].strip())
    return None


def watch(base_url: str, task_id: str) -> int:
    url = f"{base_url.rstrip('/')}/research/{task_id}/status"
    print(f"Connecting to {url}...", file=sys.stderr)

    event: str | None = None
    data: str | None = None

    try:
        with httpx.Client(timeout=None) as client, client.stream("GET", url) as response:
            for raw_line in response.iter_lines():
                parsed = _parse_sse_line(raw_line)
                if parsed is None:
                    continue
                key, value = parsed
                if key == "event":
                    event = value
                elif key == "data":
                    data = value

                if event and data is not None:
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        payload = data
                    output = {"event": event, "data": payload}
                    print(json.dumps(output, indent=2))
                    print("---")
                    event = None
                    data = None
    except httpx.HTTPStatusError as exc:
        print(f"Error: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        return 1
    except httpx.RequestError as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch research progress via SSE")
    parser.add_argument("task_id", help="Research task ID")
    parser.add_argument(
        "--url", "-u",
        default="http://localhost:8000",
        help="Base URL of the Argus API (default: http://localhost:8000)",
    )
    args = parser.parse_args()
    return watch(args.url, args.task_id)


if __name__ == "__main__":
    sys.exit(main())
