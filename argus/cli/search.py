from __future__ import annotations

import argparse
import time
from typing import Any

import httpx

from argus.cli.onboard import (
    _input_line,
    _test_duckduckgo,
    _test_firecrawl,
    _test_serpapi,
    _test_tavily,
)
from argus.llm.provider_config import (
    CONFIG_PATH,
    SEARCH_PROVIDER_DEFS,
    ProviderEntry,
    load_settings,
    save_settings,
)

C = type("C", (), {
    "CYAN": "\x1b[96m",
    "GREEN": "\x1b[92m",
    "YELLOW": "\x1b[93m",
    "RED": "\x1b[91m",
    "BOLD": "\x1b[1m",
    "DIM": "\x1b[2m",
    "RESET": "\x1b[0m",
})()


def _c(color_code: str, text: str) -> str:
    return f"{color_code}{text}{C.RESET}"


BANNER = f"""
{_c(C.CYAN, "  Search Provider Setup")}
{_c(C.DIM, "  Set which search providers are enabled and their priority order.")}
{_c(C.DIM, "  Primary = tried first, falls through on failure.")}
"""


SEARCH_TESTERS: dict[str, Any] = {
    "duckduckgo": _test_duckduckgo,
    "serpapi": _test_serpapi,
    "firecrawl": _test_firecrawl,
    "tavily": _test_tavily,
}


def _yn(prompt: str, default: bool = True) -> bool:
    suffix = _c(C.DIM, " [Y/n]") if default else _c(C.DIM, " [y/N]")
    while True:
        raw = _input_line(f"  {_c(C.CYAN, '?')} {prompt}{suffix} ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(f"  {_c(C.RED, '✗')} Answer 'y' or 'n'.")


def _text(prompt: str, default: str = "") -> str:
    suffix = _c(C.DIM, f" [{default}]") if default else ""
    while True:
        val = _input_line(f"  {_c(C.CYAN, '▸')} {prompt}{suffix} ").strip()
        if val:
            return val
        if default:
            return default
        print(f"  {_c(C.RED, '✗')} Required.")


def _secret_input(prompt: str) -> str:
    print(f"  {prompt} ", end="", flush=True)
    chars: list[str] = []
    try:
        import msvcrt
        _use_msvcrt = True
    except ImportError:
        _use_msvcrt = False

    if _use_msvcrt:
        while True:
            ch = msvcrt.getch()
            if ch in (b"\r", b"\n"):
                print()
                break
            if ch in (b"\x03", b"\x1b"):
                print()
                raise KeyboardInterrupt
            if ch in (b"\x08", b"\x7f"):
                if chars:
                    chars.pop()
                    print("\b \b", end="", flush=True)
                continue
            try:
                char = ch.decode("utf-8")
                if char.isprintable():
                    chars.append(char)
                    print(_c(C.DIM, "•"), end="", flush=True)
            except UnicodeDecodeError:
                pass
    else:
        import getpass
        val = getpass.getpass(f"  {prompt} ")
        chars = list(val)

    result = "".join(chars)
    if result:
        hidden = _c(C.DIM, "•" * max(0, len(result) - 4))
        shown = _c(C.BOLD, result[-4:])
        print(f"  {hidden}{shown}  {_c(C.GREEN, '✓')}", end="", flush=True)
        time.sleep(0.8)
        print(f"\r{' ' * (len(prompt) + len(result) + 12)}\r", end="", flush=True)

    return result


def _test(url: str, key: str, tester: Any) -> bool:
    try:
        ok, msg, _ = tester(url, key)
        if ok:
            print(f"  {_c(C.GREEN, '✓')} {msg}")
            return True
        print(f"  {_c(C.RED, '✗')} {msg}")
        return False
    except httpx.RequestError as exc:
        print(f"  {_c(C.RED, '✗')} Network error: {exc}")
        return False
    except Exception as exc:
        print(f"  {_c(C.RED, '✗')} {exc}")
        return False


def run_interactive(_args: argparse.Namespace | None = None) -> None:
    try:
        _run_interactive_impl()
    except KeyboardInterrupt:
        print(f"\n\n  {_c(C.YELLOW, 'Cancelled.')}\n")
        import sys
        sys.exit(0)


def _run_interactive_impl() -> None:
    print(BANNER)

    provider_settings = load_settings()
    changed = False

    for i, defn in enumerate(SEARCH_PROVIDER_DEFS, 1):
        ptype = defn["provider_type"]
        label = defn["display_name"]
        needs_key = defn.get("needs_api_key", False)
        existing = provider_settings.by_type(ptype)

        enabled = existing is not None and existing.enabled
        priority = existing.priority if existing else 99
        has_key = bool(existing.api_key if existing else False)

        status_parts: list[str] = []
        if enabled:
            status_parts.append(_c(C.GREEN, f"priority={priority}"))
            if needs_key:
                status_parts.append(_c(C.DIM, "[key saved]" if has_key else _c(C.RED, "[no key]")))
        else:
            status_parts.append(_c(C.DIM, "disabled"))
        status_str = "  ".join(status_parts)

        header = _c(C.CYAN + C.BOLD, f"[{i}/{len(SEARCH_PROVIDER_DEFS)}]")
        print(f"\n  {header}  {_c(C.BOLD, label)}  {status_str}")

        enable = _yn("Enable?", default=enabled)
        if enable != enabled:
            changed = True

        if not enable:
            if existing:
                existing.enabled = False
                provider_settings.upsert(existing)
            continue

        api_key = existing.api_key if existing else ""
        base_url = (
            existing.base_url
            if (existing and existing.base_url)
            else defn.get("default_base_url", "")
        )

        if needs_key and _yn("Update API key?", default=False):
            api_key = _secret_input("API Key")

        new_priority = int(
            _text("Priority (1 = primary, tried first)", default=str(priority))
        )

        if base_url and _yn("Update base URL?", default=False):
            base_url = _text("Base URL", default=base_url)

        tester = SEARCH_TESTERS.get(ptype)
        if tester:
            print()
            _test(base_url, api_key, tester)

        entry = ProviderEntry(
            provider_type=ptype,
            display_name=label,
            category="search",
            enabled=True,
            base_url=base_url,
            api_key=api_key,
            priority=new_priority,
            cost_per_million_output=defn.get("cost_per_search", 0.0),
        )
        provider_settings.upsert(entry)
        changed = True

    if changed:
        save_settings(provider_settings)
        print(f"\n  {_c(C.GREEN, '✓')} Search config saved to {_c(C.BOLD, str(CONFIG_PATH))}")
    else:
        print(f"\n  {_c(C.YELLOW, 'No changes.')}")

    print()


def run_show(_args: argparse.Namespace | None = None) -> None:
    provider_settings = load_settings()
    search_providers = [p for p in provider_settings.providers if p.category == "search"]
    if not search_providers:
        print(f"\n  {_c(C.YELLOW, 'No search providers configured.')}")
        print(f"  Run {_c(C.CYAN, 'python -m argus search')} to set them up.\n")
        return

    print(f"\n  {_c(C.CYAN + C.BOLD, 'Search Provider Config')}")
    print(f"  {_c(C.DIM, 'Order = priority (lowest first). Falls through on failure.')}\n")
    for p in sorted(search_providers, key=lambda x: x.priority):
        state = _c(C.GREEN, "enabled") if p.enabled else _c(C.RED, "disabled")
        key_status = _c(C.DIM, "✓ key") if p.api_key else _c(C.DIM, "no key")
        base = _c(C.DIM, f" [{p.base_url}]") if p.base_url else ""
        name = _c(C.BOLD, f"{p.display_name:<30}")
        print(f"  {name}  p{p.priority}  {state}  {key_status}{base}")
    print()


def add_subparser(subparsers: Any) -> None:
    parser = subparsers.add_parser("search", help="Configure search provider priority & settings")
    parser.set_defaults(func=run_interactive)

    parser = subparsers.add_parser("search-list", help="Show current search provider config")
    parser.set_defaults(func=run_show)
