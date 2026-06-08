from __future__ import annotations

import argparse
import sys
from typing import Any

from argus.cli.onboard import LLM_TESTERS, _input_line, _text
from argus.llm.provider_config import (
    CONFIG_PATH,
    DEFAULT_LLM_DEFS,
    KNOWN_MODELS,
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
{_c(C.CYAN, "  LLM Model Setup")}
{_c(C.DIM, "  View and change the model assigned to each LLM provider.")}
"""


def _pick_model(models: list[str], default: str = "") -> str:
    unique = list(dict.fromkeys(models))
    if not unique:
        return _text("Model name", default=default)

    print(f"  {_c(C.CYAN, 'Available models:')}")
    for i, m in enumerate(unique[:20], 1):
        marker = _c(C.GREEN, "← current") if m == default else ""
        print(f"    {i:>2}. {m}  {marker}")
    if len(unique) > 20:
        print(f"    … and {len(unique) - 20} more")

    val = _input_line(
        f"  {_c(C.CYAN, '▸')} Pick by number, or type a custom name [{default}]: "
    ).strip()
    if not val:
        return default
    try:
        idx = int(val) - 1
        if 0 <= idx < len(unique):
            return unique[idx]
    except ValueError:
        pass
    return val


def run_interactive(_args: argparse.Namespace | None = None) -> None:
    try:
        _run_interactive_impl()
    except KeyboardInterrupt:
        print(f"\n\n  {_c(C.YELLOW, 'Cancelled.')}\n")
        sys.exit(0)


def _run_interactive_impl() -> None:
    print(BANNER)

    provider_settings = load_settings()
    llm_providers = [p for p in provider_settings.providers if p.category == "llm" and p.enabled]
    if not llm_providers:
        print(f"  {_c(C.YELLOW, '⚠')} No LLM providers configured yet.")
        print(f"  Run {_c(C.CYAN, 'python -m argus onboard')} first.\n")
        return

    while True:
        print()
        for i, p in enumerate(llm_providers, 1):
            model = _c(C.CYAN, p.selected_model or "—")
            name = _c(C.BOLD, f"{p.display_name:<30}")
            print(f"  {i:>2}. {name}  model: {model}")
        print(f"\n  {_c(C.DIM, 'Pick a provider to change its model, or 0 to quit.')}")

        raw = _input_line(f"  {_c(C.CYAN, '▸')} Select [0-{len(llm_providers)}]: ").strip()
        if not raw:
            continue
        if raw == "0":
            break
        try:
            idx = int(raw) - 1
        except ValueError:
            continue
        if idx < 0 or idx >= len(llm_providers):
            continue

        entry = llm_providers[idx]
        defn = next(
            (d for d in DEFAULT_LLM_DEFS if d["provider_type"] == entry.provider_type), None
        )

        print(f"\n  {_c(C.BOLD, entry.display_name)}  {_c(C.DIM, f'[{entry.provider_type}]')}")
        print(f"  Current model: {_c(C.CYAN, entry.selected_model or '—')}")

        # Test connection to fetch available models
        tester = LLM_TESTERS.get(entry.provider_type)
        models: list[str] = []
        if tester and entry.api_key:
            print(f"  {_c(C.DIM, 'Testing connection to list available models…')}")
            try:
                ok, _msg, models = tester(entry.base_url, entry.api_key)
            except Exception:
                ok = False
            if not ok:
                print(f"  {_c(C.YELLOW, '⚠')} Could not fetch models (provider unreachable). "
                      f"Using known list.")
                models = []
        elif not entry.api_key:
            print(f"  {_c(C.YELLOW, '⚠')} No API key saved — showing known models only.")

        known = KNOWN_MODELS.get(entry.provider_type, [])
        all_models = list(dict.fromkeys(models + known))

        default_model = entry.selected_model or (defn.get("default_model", "") if defn else "")
        selected = _pick_model(all_models, default_model)

        if selected != entry.selected_model:
            if selected:
                entry.selected_model = selected
                provider_settings.upsert(entry)
                save_settings(provider_settings)
                print(f"  {_c(C.GREEN, '✓')} Model updated to {_c(C.BOLD, selected)}")
            else:
                print(f"  {_c(C.YELLOW, '⚠')} Model not changed.")
        else:
            print(f"  {_c(C.DIM, 'No change.')}")

    print(f"\n  {_c(C.GREEN, '✓')} Config saved to {_c(C.BOLD, str(CONFIG_PATH))}")
    print()


def run_show(_args: argparse.Namespace | None = None) -> None:
    provider_settings = load_settings()
    llm_providers = [p for p in provider_settings.providers if p.category == "llm" and p.enabled]
    if not llm_providers:
        print(f"\n  {_c(C.YELLOW, 'No LLM providers configured.')}")
        print(f"  Run {_c(C.CYAN, 'python -m argus onboard')} to set them up.\n")
        return

    print(f"\n  {_c(C.CYAN + C.BOLD, 'LLM Provider Models')}\n")
    for p in llm_providers:
        name = _c(C.BOLD, f"{p.display_name:<30}")
        model = _c(C.CYAN, p.selected_model or "—")
        base = _c(C.DIM, f" [{p.base_url}]") if p.base_url else ""
        print(f"  {name}  {model}{base}")
    print()


def add_subparser(subparsers: Any) -> None:
    parser = subparsers.add_parser("models", help="Configure LLM provider models")
    parser.set_defaults(func=run_interactive)

    parser = subparsers.add_parser("models-list", help="Show current LLM provider models")
    parser.set_defaults(func=run_show)
