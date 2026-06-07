from __future__ import annotations

import argparse
import sys
from typing import Any

from argus.cli.onboard import _input_line
from argus.llm.profile import (
    ALL_STAGES,
    PROFILE_PATH,
    STAGE_LABELS,
    StageProfile,
    load_profile,
    save_profile,
)
from argus.llm.provider_config import load_settings

C = type("C", (), {
    "CYAN": "\x1b[96m",
    "GREEN": "\x1b[92m",
    "YELLOW": "\x1b[93m",
    "RED": "\x1b[91m",
    "BOLD": "\x1b[1m",
    "DIM": "\x1b[2m",
    "RESET": "\x1b[0m",
})()


def c(color_code: str, text: str) -> str:
    return f"{color_code}{text}{C.RESET}"


BANNER = f"""
{c(C.CYAN, "  Stage Profile Setup")}
{c(C.DIM, "  Assign specific providers + models to each research stage.")}
{c(C.DIM, "  Leave a stage unassigned to use its default routing.")}
"""


def _pick(prompt: str, options: list[str], default: str = "") -> str:
    for i, opt in enumerate(options, 1):
        tag = c(C.GREEN, "  ← default") if opt == default else ""
        print(f"    {c(C.YELLOW, str(i) + '.')} {opt}{tag}")
    print(f"    {c(C.YELLOW, str(len(options) + 1) + '.')} None / skip")

    while True:
        raw = _input_line(f"  {c(C.CYAN, '▸')} {prompt} {c(C.DIM, '[1]')} ").strip()
        if not raw:
            return default if default else options[0]
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
            if idx == len(options) + 1:
                return ""
        except ValueError:
            pass
        print(f"  {c(C.RED, '✗')} Invalid choice.")


def _text(prompt: str, default: str = "") -> str:
    suffix = c(C.DIM, f" [{default}]") if default else ""
    while True:
        val = _input_line(f"  {c(C.CYAN, '▸')} {prompt}{suffix} ").strip()
        if val:
            return val
        if default:
            return default
        print(f"  {c(C.RED, '✗')} Required.")


def run_interactive(_args: argparse.Namespace | None = None) -> None:
    try:
        _run_interactive_impl()
    except KeyboardInterrupt:
        print(f"\n\n  {c(C.YELLOW, 'Cancelled. No changes saved.')}\n")
        sys.exit(0)


def _run_interactive_impl() -> None:
    print(BANNER)

    provider_settings = load_settings()
    enabled_llms = provider_settings.get_enabled("llm")
    if not enabled_llms:
        print(f"  {c(C.YELLOW, '⚠')} No LLM providers configured yet.")
        print(f"  Run {c(C.CYAN, 'python -m argus onboard')} first.\n")
        return

    profile = load_profile()
    changed = False

    provider_types = [p.provider_type for p in enabled_llms]

    print(f"  {c(C.CYAN + C.BOLD, 'Available providers:')}")
    for p in enabled_llms:
        model_tag = c(C.DIM, f" [{p.selected_model}]") if p.selected_model else ""
        print(f"    {c(C.GREEN, '✓')} {p.display_name}{model_tag}")

    print(f"\n  {c(C.CYAN + C.BOLD, 'Stage-by-stage assignment:')}")
    print(f"  {c(C.DIM, '(pick a provider + model per stage, or skip for defaults)')}\n")

    for stage in ALL_STAGES:
        existing = profile.by_task_type(stage)
        label = STAGE_LABELS[stage]
        if existing:
            pv, md = existing.provider_type, existing.model or "default"
            status = c(C.GREEN, f"{pv}/{md}")
        else:
            status = c(C.DIM, "(default)")
        print(f"  {c(C.CYAN + C.BOLD, '─── ' + label + ' ───')}  {status}")

        use_custom = _yn("Assign a specific provider?", default=existing is not None)
        if use_custom:
            if existing:
                clear = _yn("Remove assignment and use default routing instead?", default=False)
                if clear:
                    profile.remove(stage)
                    changed = True
                    continue
                p_default = existing.provider_type
            else:
                p_default = ""

            ptype = _pick("Provider:", provider_types, default=p_default)
            if not ptype:
                continue

            selected_entry = next((p for p in enabled_llms if p.provider_type == ptype), None)
            known_models = selected_entry.selected_model or ""

            print(f"  {c(C.DIM, '(blank = use provider default model)')}")
            if existing and existing.provider_type == ptype:
                m_default = existing.model
            else:
                m_default = known_models
            model = _text("Model", default=m_default)

            profile.upsert(stage, ptype, model)
            changed = True

    if changed:
        save_profile(profile)
        path_str = str(PROFILE_PATH)
        print(f"\n  {c(C.GREEN, '✓')} Stage profile saved to {c(C.BOLD, path_str)}")
    else:
        print(f"\n  {c(C.YELLOW, 'No changes.')}")

    print()


def _yn(prompt: str, default: bool = True) -> bool:
    suffix = c(C.DIM, " [Y/n]") if default else c(C.DIM, " [y/N]")
    while True:
        raw = _input_line(f"  {c(C.CYAN, '?')} {prompt}{suffix} ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(f"  {c(C.RED, '✗')} Answer 'y' or 'n'.")


def run_show(_args: argparse.Namespace | None = None) -> None:
    profile = load_profile()
    if not profile.assignments:
        print(f"  {c(C.YELLOW, 'No stage assignments configured.')}")
        print(f"  Run {c(C.CYAN, 'python -m argus profile')} to set them up.\n")
        return

    print(f"\n  {c(C.CYAN + C.BOLD, 'Stage Profile')}")
    for a in profile.assignments:
        model_tag = c(C.DIM, f" [{a.model}]") if a.model else ""
        print(f"    {a.task_type:<20} → {c(C.GREEN, a.provider_type)}{model_tag}")
    print()


def run_clear(_args: argparse.Namespace | None = None) -> None:
    profile = StageProfile()
    save_profile(profile)
    print(f"\n  {c(C.GREEN, '✓')} Stage profile cleared. All stages will use defaults.\n")


def add_subparser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "profile", help="Configure stage-specific provider/model assignments"
    )
    parser.set_defaults(func=run_interactive)

    parser = subparsers.add_parser(
        "profile-list", help="Show current stage profile assignments"
    )
    parser.set_defaults(func=run_show)

    parser = subparsers.add_parser(
        "profile-clear", help="Clear all stage profile assignments"
    )
    parser.set_defaults(func=run_clear)
