from __future__ import annotations

import getpass
import sys
from typing import Any

import httpx

from argus.llm.provider_config import (
    CONFIG_PATH,
    DEFAULT_LLM_DEFS,
    KNOWN_MODELS,
    SEARCH_PROVIDER_DEFS,
    ProviderEntry,
    ProviderSettings,
    load_settings,
    save_settings,
)

WELCOME = """

  ╭──────────────────────────────────────────────╮
  │           Argus Provider Setup               │
  │                                              │
  │  Configure LLM providers AND search/tool     │
  │  providers. Pick which ones to use, enter    │
  │  API keys, choose models, and set priority.  │
  │                                              │
  │  Keys are tested immediately. Invalid keys   │
  │  will be rejected and you can retry.         │
  │                                              │
  │  Press Ctrl+C to exit at any time.           │
  ╰──────────────────────────────────────────────╯

"""


# ── Helpers ──────────────────────────────────────────────────────────


def _yn(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        raw = input(prompt + suffix + " ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer 'y' or 'n'.")


def _text(prompt: str, default: str = "", *, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            val = getpass.getpass(prompt + suffix + " ")
        else:
            val = input(prompt + suffix + " ").strip()
        if val:
            return val
        if default:
            return default
        print("  This field is required.")


def _pick_model(models: list[str], default: str) -> str:
    if not models:
        raw = input(f"  Model name [{default}]: ").strip()
        return raw or default

    print("  Available models:")
    for i, m in enumerate(models, 1):
        tag = " (default)" if m == default else ""
        print(f"    {i}. {m}{tag}")
    print(f"    {len(models) + 1}. Type custom name")

    while True:
        raw = input("  Select [1]: ").strip()
        if not raw:
            return models[0] if default not in models else default
        try:
            idx = int(raw)
            if 1 <= idx <= len(models):
                return models[idx - 1]
            if idx == len(models) + 1:
                return _text("  Enter model name", default=default)
        except ValueError:
            pass
        print("  Invalid choice.")


# ── LLM connection testers ────────────────────────────────────────────


def _test_groq(url: str, key: str) -> tuple[bool, str, list[str]]:
    resp = httpx.get(
        url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=15,
    )
    if resp.status_code == 200:
        models = [m["id"] for m in resp.json()["data"]]
        return True, "Connected", models
    body = resp.text[:300]
    if resp.status_code == 401:
        return False, "Invalid API key (401)", []
    return False, f"HTTP {resp.status_code}: {body}", []


def _test_openrouter(url: str, key: str) -> tuple[bool, str, list[str]]:
    resp = httpx.get(
        url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=15,
    )
    if resp.status_code == 200:
        models = [m["id"] for m in resp.json()["data"]]
        return True, "Connected", models
    body = resp.text[:300]
    if resp.status_code == 401:
        return False, "Invalid API key (401)", []
    return False, f"HTTP {resp.status_code}: {body}", []


def _test_ollama(url: str, _key: str = "") -> tuple[bool, str, list[str]]:
    resp = httpx.get(url.rstrip("/") + "/api/tags", timeout=5)
    if resp.status_code == 200:
        models = [m["name"] for m in resp.json()["models"]]
        return True, "Connected", models
    return False, f"HTTP {resp.status_code}", []


def _test_openai_compatible(url: str, key: str) -> tuple[bool, str, list[str]]:
    resp = httpx.get(
        url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=15,
    )
    if resp.status_code == 200:
        models = [m["id"] for m in resp.json()["data"]]
        return True, "Connected", models
    body = resp.text[:300]
    return False, f"HTTP {resp.status_code}: {body}", []


LLM_TESTERS: dict[str, Any] = {
    "groq": _test_groq,
    "openrouter": _test_openrouter,
    "ollama": _test_ollama,
    "openai_compatible": _test_openai_compatible,
}


# ── Search connection testers ─────────────────────────────────────────


def _test_serpapi(url: str, key: str) -> tuple[bool, str, None]:
    resp = httpx.get(
        url.rstrip("/") + "/search",
        params={"q": "test", "api_key": key, "num": 1},
        timeout=15,
    )
    if resp.status_code == 200:
        return True, "Connected", None
    if resp.status_code == 401:
        return False, "Invalid API key (401)", None
    body = resp.text[:200]
    return False, f"HTTP {resp.status_code}: {body}", None


def _test_firecrawl(url: str, key: str) -> tuple[bool, str, None]:
    resp = httpx.post(
        url.rstrip("/") + "/v2/search",
        json={"query": "test", "sources": ["web"], "limit": 1, "scrapeOptions": {"formats": []}},
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=15,
    )
    if resp.status_code == 200:
        return True, "Connected", None
    if resp.status_code in (401, 403):
        return False, "Invalid API key", None
    body = resp.text[:200]
    return False, f"HTTP {resp.status_code}: {body}", None


def _test_duckduckgo(_url: str = "", _key: str = "") -> tuple[bool, str, None]:
    return True, "Always available (no key needed)", None


SEARCH_TESTERS: dict[str, Any] = {
    "serpapi": _test_serpapi,
    "firecrawl": _test_firecrawl,
    "duckduckgo": _test_duckduckgo,
}


# ── LLM provider wizard ───────────────────────────────────────────────


def _configure_llm(
    defn: dict[str, Any],
    existing: ProviderEntry | None,
) -> ProviderEntry | None:
    ptype = defn["provider_type"]
    label = defn["display_name"]

    already = existing is not None and existing.enabled and existing.api_key
    if already and not _yn(
        f"\n── {label} ──\n  Reconfigure? (current keys are saved)", default=False
    ):
        return existing

    if not _yn(f"\n── {label} ──\n  Enable this provider?", default=True):
        if existing is not None:
            existing.enabled = False
            return existing
        return None

    base_url = _text(
        "  Base URL",
        default=existing.base_url if (existing and existing.base_url) else defn["default_base_url"],
    )

    if ptype == "ollama":
        api_key = existing.api_key if existing else ""
    else:
        api_key = _text(
            "  API Key",
            default=existing.api_key if existing else "",
            secret=True,
        )

    # Test connection with retries
    tester = LLM_TESTERS[ptype]
    models: list[str] = []
    for attempt in range(3):
        print("  Testing connection...", end=" ")
        sys.stdout.flush()
        try:
            ok, msg, models = tester(base_url, api_key)
        except httpx.RequestError as exc:
            ok, msg = False, f"Network error: {exc}"

        if ok:
            print(f"✅ {msg}")
            break
        print(f"❌ {msg}")
        if attempt < 2:
            if not _yn("  Retry?", default=True):
                break
            if ptype != "ollama":
                api_key = _text("  API Key", secret=True)
            base_url = _text("  Base URL", default=base_url)
        else:
            print("  Skipping this provider after 3 failed attempts.")
            return None

    # Model selection
    known = KNOWN_MODELS.get(ptype, [])
    all_models = list(dict.fromkeys(models + known))
    default_model = (
        existing.selected_model
        if (existing and existing.selected_model)
        else defn["default_model"]
    )
    selected = _pick_model(all_models, default_model)

    return ProviderEntry(
        provider_type=ptype,
        display_name=label,
        category="llm",
        enabled=True,
        base_url=base_url,
        api_key=api_key,
        selected_model=selected,
        priority=99,
        cost_per_million_input=defn["cost_input"],
        cost_per_million_output=defn["cost_output"],
    )


# ── Search provider wizard ────────────────────────────────────────────


def _configure_search(
    defn: dict[str, Any],
    existing: ProviderEntry | None,
) -> ProviderEntry | None:
    ptype = defn["provider_type"]
    label = defn["display_name"]
    needs_key = defn.get("needs_api_key", True)

    already = existing is not None and existing.enabled
    if already and not _yn(
        f"\n── {label} ──\n  Reconfigure?", default=False
    ):
        return existing

    if not _yn(f"\n── {label} ──\n  Enable this provider?", default=True):
        if existing is not None:
            existing.enabled = False
            return existing
        return None

    api_key = existing.api_key if existing else ""
    base_url = (
        existing.base_url
        if (existing and existing.base_url)
        else defn.get("default_base_url", "")
    )

    if needs_key:
        api_key = _text(
            "  API Key",
            default=api_key,
            secret=True,
        )

    if defn.get("default_base_url"):
        base_url = _text("  Base URL", default=base_url)

    # Test connection
    tester = SEARCH_TESTERS[ptype]
    for attempt in range(3):
        print("  Testing connection...", end=" ")
        sys.stdout.flush()
        try:
            ok, msg, _models = tester(base_url, api_key)
        except httpx.RequestError as exc:
            ok, msg = False, f"Network error: {exc}"

        if ok:
            print(f"✅ {msg}")
            break
        print(f"❌ {msg}")
        if attempt < 2:
            if not _yn("  Retry?", default=True):
                break
            if needs_key:
                api_key = _text("  API Key", secret=True)
            if defn.get("default_base_url"):
                base_url = _text("  Base URL", default=base_url)
        else:
            print("  Skipping this provider after 3 failed attempts.")
            return None

    return ProviderEntry(
        provider_type=ptype,
        display_name=label,
        category="search",
        enabled=True,
        base_url=base_url,
        api_key=api_key,
        priority=99,
        cost_per_million_output=defn.get("cost_per_search", 0.0),
    )


# ── Priority ordering ─────────────────────────────────────────────────


def _set_priorities(settings: ProviderSettings, category: str) -> None:
    enabled = settings.get_enabled(category)
    if len(enabled) <= 1:
        return

    label = "LLM" if category == "llm" else "Search"
    print(f"\n── {label} Provider Priority ──")
    print("  Set priority order. 1 = primary (tried first).")
    for i, p in enumerate(enabled, 1):
        extra = f" [{p.selected_model}]" if p.selected_model else ""
        print(f"    {i}. {p.display_name}{extra}")

    for p in enabled:
        while True:
            raw = input(f"  Priority for '{p.display_name}' [{p.priority}]: ").strip()
            if not raw:
                break
            try:
                p.priority = int(raw)
                break
            except ValueError:
                print("  Enter a number.")


# ── .env updater ──────────────────────────────────────────────────────


ENV_MAP: dict[str, dict[str, str]] = {
    "groq": {
        "api_key": "ARGUS_GROQ_API_KEY",
        "base_url": "ARGUS_GROQ_BASE_URL",
        "selected_model": "ARGUS_GROQ_MODEL",
    },
    "openrouter": {
        "api_key": "ARGUS_OPENROUTER_API_KEY",
        "base_url": "ARGUS_OPENROUTER_BASE_URL",
        "selected_model": "ARGUS_OPENROUTER_MODEL",
    },
    "ollama": {"base_url": "ARGUS_OLLAMA_BASE_URL", "selected_model": "ARGUS_OLLAMA_MODEL"},
    "openai_compatible": {
        "api_key": "ARGUS_OPENAI_COMPATIBLE_API_KEY",
        "base_url": "ARGUS_OPENAI_COMPATIBLE_BASE_URL",
        "selected_model": "ARGUS_OPENAI_COMPATIBLE_MODEL",
    },
    "serpapi": {"api_key": "ARGUS_SERPAPI_API_KEY"},
    "firecrawl": {"api_key": "ARGUS_FIRECRAWL_API_KEY"},
}


def _update_dotenv(settings: ProviderSettings) -> None:
    from pathlib import Path

    env_path = Path(".env")
    if not env_path.exists():
        if not _yn("\n  No .env file found. Create one?", default=True):
            return
        env_path.write_text("", encoding="utf-8")

    lines = env_path.read_text("utf-8").splitlines(keepends=True)

    def set_key(key: str, value: str) -> None:
        nonlocal lines
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(key + "=") or stripped.startswith("# " + key + "="):
                lines[i] = f"{key}={value}\n"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}\n")

    count = 0
    for p in settings.providers:
        if not p.enabled:
            continue
        mapping = ENV_MAP.get(p.provider_type)
        if not mapping:
            continue
        for field, env_key in mapping.items():
            val = getattr(p, field, "")
            if val:
                set_key(env_key, val)
                count += 1

    env_path.write_text("".join(lines), "utf-8")
    print(f"  ✅ Updated {env_path.name} ({count} values)")


# ── Main ──────────────────────────────────────────────────────────────


def run_onboard() -> None:
    try:
        _run_onboard_impl()
    except KeyboardInterrupt:
        print("\n\n  Setup cancelled. No changes saved.\n")
        sys.exit(0)


def _run_onboard_impl() -> None:
    print(WELCOME)

    settings = load_settings()
    dirty = False

    # ── LLM providers ──
    print("\n  ─── LLM Providers ───\n")
    for defn in DEFAULT_LLM_DEFS:
        ptype = defn["provider_type"]
        existing = settings.by_type(ptype)
        result = _configure_llm(defn, existing)
        if result is not None:
            settings.upsert(result)
            dirty = True

    # ── Search providers ──
    print("\n  ─── Search / Tool Providers ───\n")
    for defn in SEARCH_PROVIDER_DEFS:
        ptype = defn["provider_type"]
        existing = settings.by_type(ptype)
        result = _configure_search(defn, existing)
        if result is not None:
            settings.upsert(result)
            dirty = True

    if not dirty:
        print("No providers configured. Exiting.\n")
        return

    _set_priorities(settings, "llm")
    _set_priorities(settings, "search")
    save_settings(settings)
    print(f"\n  ✅ Configuration saved to {CONFIG_PATH}")

    if _yn("\n  Also write keys to .env file?", default=True):
        _update_dotenv(settings)

    print("\n  Done! You can re-run this anytime with:")
    print("    python -m argus onboard\n")
