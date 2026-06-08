from __future__ import annotations

import sys
import time
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

# ── Terminal colors ───────────────────────────────────────────────────

C = type("C", (), {
    "CYAN": "\x1b[96m",
    "GREEN": "\x1b[92m",
    "YELLOW": "\x1b[93m",
    "RED": "\x1b[91m",
    "BLUE": "\x1b[94m",
    "MAGENTA": "\x1b[95m",
    "BOLD": "\x1b[1m",
    "DIM": "\x1b[2m",
    "RESET": "\x1b[0m",
    "ERASE_LINE": "\x1b[2K\r",
})()


def c(color_code: str, text: str) -> str:
    return f"{color_code}{text}{C.RESET}"


_N = lambda s: c(C.CYAN, s)  # noqa: E731
_B = lambda s: c(C.BOLD + C.CYAN, s)  # noqa: E731
_Y = lambda s: c(C.YELLOW, s)  # noqa: E731
_L = _N("\u2551")
_BX_TOP = _N("\u2554\u2550" * 28 + "\u2557")
_BX_BOT = _N("\u255a\u2550" * 28 + "\u255d")
_BX_SP = _L + " " * 55 + _L
_BX_L1 = _L + "   " + _B("ARGUS \u2014 Provider Setup Wizard") + " " * 23 + _L
_BX_L2 = _L + "   Configure LLM + search providers. API keys " + " " * 9 + _L
_BX_L3 = _L + "   are tested instantly \u2014 no guessing.    " + " " * 13 + _L
_BX_L4 = (
    _L
    + "   Press "
    + _Y("Esc/Ctrl+C")
    + " to exit \u00b7 saved to providers.json"
    + " " * 2
    + _L
)

BANNER = (
    _N("    ") + _BX_TOP + "\n"
    + _N("    ") + _BX_L1 + "\n"
    + _N("    ") + _BX_SP + "\n"
    + _N("    ") + _BX_L2 + "\n"
    + _N("    ") + _BX_L3 + "\n"
    + _N("    ") + _BX_SP + "\n"
    + _N("    ") + _BX_L4 + "\n"
    + _N("    ") + _BX_BOT
)




# ── Helpers ──────────────────────────────────────────────────────────


def _input_line(prompt: str) -> str:
    """Read a line of input; Esc or Ctrl+C raises KeyboardInterrupt."""
    try:
        import msvcrt  # noqa: F811
    except ImportError:
        return input(prompt)

    print(prompt, end="", flush=True)
    chars: list[str] = []
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
                print(char, end="", flush=True)
        except UnicodeDecodeError:
            pass
    return "".join(chars)


def _secret_input(prompt: str) -> str:
    """Read a secret value, displaying • for each character typed.

    After Enter, briefly shows the last 4 characters so the user
    can confirm their input, then clears the confirmation.
    """
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
                    print(c(C.DIM, "•"), end="", flush=True)
            except UnicodeDecodeError:
                pass
    else:
        import getpass
        val = getpass.getpass(f"  {prompt} ")
        chars = list(val)

    result = "".join(chars)
    if result:
        hidden = c(C.DIM, "•" * max(0, len(result) - 4))
        shown = c(C.BOLD, result[-4:])
        print(f"  {hidden}{shown}  {c(C.GREEN, '✓')}", end="", flush=True)
        time.sleep(0.8)
        print(f"\r{' ' * (len(prompt) + len(result) + 12)}\r", end="", flush=True)

    return result


def _yn(prompt: str, default: bool = True) -> bool:
    suffix = c(C.DIM, " [Y/n]") if default else c(C.DIM, " [y/N]")
    badge = c(C.CYAN, "?")
    while True:
        raw = _input_line(f"  {badge} {prompt}{suffix} ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(f"  {c(C.RED, '✗')} Please answer 'y' or 'n'.")


def _text(prompt: str, default: str = "") -> str:
    suffix = c(C.DIM, f" [{default}]") if default else ""
    badge = c(C.CYAN, "▸")
    while True:
        val = _input_line(f"  {badge} {prompt}{suffix} ").strip()
        if val:
            return val
        if default:
            return default
        print(f"  {c(C.RED, '✗')} This field is required.")


def _pick_model(models: list[str], default: str) -> str:
    if not models:
        raw = _input_line(f"  {c(C.CYAN, '▸')} Model name {c(C.DIM, f'[{default}]')} ").strip()
        return raw or default

    badge = c(C.CYAN, "▸")
    print(f"  {badge} Available models:")
    for i, m in enumerate(models, 1):
        tag = c(C.GREEN, "  ← default") if m == default else ""
        print(f"    {c(C.YELLOW, str(i) + '.')} {m}{tag}")
    print(f"    {c(C.YELLOW, str(len(models) + 1) + '.')} Type custom name")

    while True:
        raw = _input_line(f"  {badge} Select {c(C.DIM, '[1]')} ").strip()
        if not raw:
            return models[0] if default not in models else default
        try:
            idx = int(raw)
            if 1 <= idx <= len(models):
                return models[idx - 1]
            if idx == len(models) + 1:
                return _text("Model name", default=default)
        except ValueError:
            pass
        print(f"  {c(C.RED, '✗')} Invalid choice.")


# ── Spinner ──────────────────────────────────────────────────────────


class Spinner:
    _chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str = "") -> None:
        self._message = message
        self._idx = 0

    def tick(self) -> None:
        self._idx = (self._idx + 1) % len(self._chars)
        print(f"\r  {c(C.CYAN, self._chars[self._idx])} {self._message}", end="", flush=True)

    def done(self, ok: bool = True, msg: str = "") -> None:
        icon = c(C.GREEN, "✓") if ok else c(C.RED, "✗")
        extra = f" {c(C.DIM, msg)}" if msg else ""
        print(f"\r  {icon} {self._message}{extra}" + " " * 10)


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


def _test_anthropic(url: str, key: str) -> tuple[bool, str, list[str]]:
    resp = httpx.get(
        url.rstrip("/") + "/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        timeout=15,
    )
    if resp.status_code == 200:
        models = [m["id"] for m in resp.json()["data"]]
        return True, "Connected", models
    body = resp.text[:300]
    if resp.status_code == 401:
        return False, "Invalid API key (401)", []
    return False, f"HTTP {resp.status_code}: {body}", []


def _test_google_ai_studio(url: str, key: str) -> tuple[bool, str, list[str]]:
    resp = httpx.get(
        f"{url.rstrip('/')}/models",
        params={"key": key},
        timeout=15,
    )
    if resp.status_code == 200:
        models = [m["name"].replace("models/", "") for m in resp.json().get("models", [])]
        return True, "Connected", models
    body = resp.text[:300]
    if resp.status_code in (401, 403):
        return False, "Invalid API key", []
    return False, f"HTTP {resp.status_code}: {body}", []


LLM_TESTERS: dict[str, Any] = {
    "groq": _test_groq,
    "openrouter": _test_openrouter,
    "ollama": _test_ollama,
    "openai": _test_openai_compatible,
    "anthropic": _test_anthropic,
    "google_ai_studio": _test_google_ai_studio,
    "litellm": _test_openai_compatible,
    "together_ai": _test_openai_compatible,
    "deepseek": _test_openai_compatible,
    "nvidia": _test_openai_compatible,
    "custom_openai": _test_openai_compatible,
    "openai_compatible": _test_openai_compatible,
}


# ── Search connection testers ─────────────────────────────────────────


def _test_tavily(url: str, key: str) -> tuple[bool, str, None]:
    resp = httpx.post(
        url.rstrip("/") + "/search",
        json={"query": "test", "api_key": key, "max_results": 1},
        timeout=15,
    )
    if resp.status_code == 200:
        return True, "Connected", None
    if resp.status_code == 401:
        return False, "Invalid API key (401)", None
    body = resp.text[:200]
    return False, f"HTTP {resp.status_code}: {body}", None


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
    "tavily": _test_tavily,
}


# ── LLM provider wizard ───────────────────────────────────────────────


def _configure_llm(
    defn: dict[str, Any],
    existing: ProviderEntry | None,
    index: int,
    total: int,
) -> ProviderEntry | None:
    ptype = defn["provider_type"]
    label = defn["display_name"]

    if ptype == "custom_openai":
        fallback = existing.display_name if existing else ""
        is_placeholder = fallback in ("", "Custom (OpenAI-compatible)")
        custom_name = _text(
            "Provider name",
            default="" if is_placeholder else fallback,
        )
        if custom_name:
            label = custom_name

    already = existing is not None and existing.enabled and existing.api_key
    status = c(C.GREEN, "✓ enabled") if already else c(C.DIM, "not configured")
    print(f"\n  {c(C.CYAN + C.BOLD, f'[{index}/{total}]')}  {c(C.BOLD, label)}  {status}")

    if already and not _yn("Reconfigure? (current keys are saved)", default=False):
        return existing

    if not _yn("Enable this provider?", default=True):
        if existing is not None:
            existing.enabled = False
            return existing
        return None

    if ptype == "ollama":
        is_local = _yn("Use local Ollama (no API key needed)?", default=True)
        if is_local:
            api_key = existing.api_key if existing else ""
            base_url = _text(
                "Base URL",
                default=existing.base_url if (existing and existing.base_url) else "http://localhost:11434",
            )
        else:
            base_url = _text(
                "Base URL",
                default=(
                    existing.base_url
                    if (existing and existing.base_url)
                    else defn["default_base_url"]
                ),
            )
            api_key = _secret_input("API Key" if not existing else "API Key (blank = keep current)")
    else:
        base_url = _text(
            "Base URL",
            default=(
                existing.base_url
                if (existing and existing.base_url)
                else defn["default_base_url"]
            ),
        )
        api_key = _secret_input("API Key" if not existing else "API Key (blank = keep current)")

    if not api_key and existing and existing.api_key:
        api_key = existing.api_key

    # Test connection with spinner
    tester = LLM_TESTERS[ptype]
    spinner = Spinner("Testing connection…")
    models: list[str] = []
    connected = False
    for attempt in range(3):
        spinner.tick()
        try:
            ok, msg, models = tester(base_url, api_key)
        except httpx.RequestError as exc:
            ok, msg = False, f"Network error: {exc}"
        except Exception as exc:
            ok, msg = False, str(exc)

        if ok:
            spinner.done(True, msg)
            connected = True
            break
        spinner.done(False, msg)
        if attempt < 2:
            if not _yn("Retry?", default=True):
                break
            if ptype != "ollama":
                api_key = _secret_input("API Key")
            base_url = _text("Base URL", default=base_url)

    if not connected:
        if ptype == "custom_openai":
            print(f"  {c(C.YELLOW, '⚠')} Connection failed — enter model ID manually.")
            selected = _text("Model name")
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
        print(f"  {c(C.YELLOW, '⚠')} Skipping after 3 failed attempts.")
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
    status = c(C.GREEN, "✓ enabled") if already else c(C.DIM, "not configured")
    print(f"\n  {c(C.BOLD, label)}  {status}")

    if already and not _yn("Reconfigure?", default=False):
        return existing

    if not _yn("Enable this provider?", default=True):
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
        api_key = _secret_input("API Key" if not api_key else "API Key (blank = keep current)")
        if not api_key and existing and existing.api_key:
            api_key = existing.api_key

    if defn.get("default_base_url"):
        base_url = _text("Base URL", default=base_url)

    # Test connection with spinner
    tester = SEARCH_TESTERS[ptype]
    spinner = Spinner("Testing connection…")
    for attempt in range(3):
        spinner.tick()
        try:
            ok, msg, _unused = tester(base_url, api_key)
        except httpx.RequestError as exc:
            ok, msg = False, f"Network error: {exc}"
        except Exception as exc:
            ok, msg = False, str(exc)

        if ok:
            spinner.done(True, msg)
            break
        spinner.done(False, msg)
        if attempt < 2:
            if not _yn("Retry?", default=True):
                break
            if needs_key:
                api_key = _secret_input("API Key")
            if defn.get("default_base_url"):
                base_url = _text("Base URL", default=base_url)
        else:
            print(f"  {c(C.YELLOW, '⚠')} Skipping after 3 failed attempts.")
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
    print(f"\n  {c(C.CYAN + C.BOLD, '─── ' + label + ' Provider Priority ───')}")
    print(f"  {c(C.DIM, 'Set priority (1 = primary, tried first).')}")
    for p in enabled:
        extra = c(C.DIM, f" [{p.selected_model}]") if p.selected_model else ""
        current = c(C.YELLOW, str(p.priority))
        lbl = c(C.BOLD, p.display_name)
        raw = input(f"  {c(C.CYAN, '▸')} Priority for '{lbl}'{extra} [{current}]: ").strip()
        if raw:
            try:
                p.priority = int(raw)
            except ValueError:
                print(f"  {c(C.RED, '✗')} Enter a number.")


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
    "openai": {
        "api_key": "ARGUS_OPENAI_API_KEY",
        "base_url": "ARGUS_OPENAI_BASE_URL",
        "selected_model": "ARGUS_OPENAI_MODEL",
    },
    "anthropic": {
        "api_key": "ARGUS_ANTHROPIC_API_KEY",
        "base_url": "ARGUS_ANTHROPIC_BASE_URL",
        "selected_model": "ARGUS_ANTHROPIC_MODEL",
    },
    "google_ai_studio": {
        "api_key": "ARGUS_GOOGLE_AI_STUDIO_API_KEY",
        "base_url": "ARGUS_GOOGLE_AI_STUDIO_BASE_URL",
        "selected_model": "ARGUS_GOOGLE_AI_STUDIO_MODEL",
    },
    "litellm": {
        "api_key": "ARGUS_LITELLM_API_KEY",
        "base_url": "ARGUS_LITELLM_BASE_URL",
        "selected_model": "ARGUS_LITELLM_MODEL",
    },
    "together_ai": {
        "api_key": "ARGUS_TOGETHER_AI_API_KEY",
        "base_url": "ARGUS_TOGETHER_AI_BASE_URL",
        "selected_model": "ARGUS_TOGETHER_AI_MODEL",
    },
    "deepseek": {
        "api_key": "ARGUS_DEEPSEEK_API_KEY",
        "base_url": "ARGUS_DEEPSEEK_BASE_URL",
        "selected_model": "ARGUS_DEEPSEEK_MODEL",
    },
    "nvidia": {
        "api_key": "ARGUS_NVIDIA_API_KEY",
        "base_url": "ARGUS_NVIDIA_BASE_URL",
        "selected_model": "ARGUS_NVIDIA_MODEL",
    },
    "custom_openai": {
        "api_key": "ARGUS_CUSTOM_OPENAI_API_KEY",
        "base_url": "ARGUS_CUSTOM_OPENAI_BASE_URL",
        "selected_model": "ARGUS_CUSTOM_OPENAI_MODEL",
    },
    "openai_compatible": {
        "api_key": "ARGUS_OPENAI_COMPATIBLE_API_KEY",
        "base_url": "ARGUS_OPENAI_COMPATIBLE_BASE_URL",
        "selected_model": "ARGUS_OPENAI_COMPATIBLE_MODEL",
    },
    "serpapi": {"api_key": "ARGUS_SERPAPI_API_KEY"},
    "firecrawl": {"api_key": "ARGUS_FIRECRAWL_API_KEY"},
    "tavily": {"api_key": "ARGUS_TAVILY_API_KEY"},
}


def _update_dotenv(settings: ProviderSettings) -> None:
    from pathlib import Path

    env_path = Path(".env")
    if not env_path.exists():
        if not _yn("No .env file found. Create one?", default=True):
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
    print(f"  {c(C.GREEN, '✓')} Updated {env_path.name} ({count} values)")


# ── Multi-select provider picker ─────────────────────────────────────


def _select_providers(
    title: str, defs: list[dict[str, Any]], existing: ProviderSettings
) -> list[int]:
    """Show numbered list of providers, let user pick which to configure.

    Returns indices into *defs* that the user selected.
    Supports: ``all``, ``none``, ``1,3,5``, ``1-5``, ``1 3 5``.
    """
    print(f"\n  {c(C.CYAN + C.BOLD, f'─── {title} ───')}")
    for i, defn in enumerate(defs, 1):
        ptype = defn["provider_type"]
        ex = existing.by_type(ptype)
        already = ex is not None and ex.enabled and bool(ex.api_key)
        status = c(C.GREEN, "✓") if already else c(C.DIM, " ")
        print(f"    {c(C.YELLOW, str(i) + '.')} [{status}] {defn['display_name']}")

    sel_prompt = f"  {c(C.CYAN, '▸')} Select (e.g. '1,3,5', '1-5', or 'all'): "
    raw = _input_line(sel_prompt).strip().lower()
    if raw in ("", "all"):
        return list(range(len(defs)))
    if raw in ("none", "0"):
        return []

    selected: set[int] = set()
    for part in raw.replace(",", " ").split():
        if "-" in part:
            try:
                a_s, b_s = part.split("-", 1)
                a, b = int(a_s), int(b_s)
                for n in range(a, b + 1):
                    if 1 <= n <= len(defs):
                        selected.add(n - 1)
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= len(defs):
                    selected.add(n - 1)
            except ValueError:
                pass
    return sorted(selected)


# ── Main ──────────────────────────────────────────────────────────────


def run_onboard() -> None:
    try:
        _run_onboard_impl()
    except KeyboardInterrupt:
        print(f"\n\n  {c(C.YELLOW, 'Setup cancelled. No changes saved.')}\n")
        sys.exit(0)


def _run_onboard_impl() -> None:
    print(BANNER)

    provider_settings = load_settings()
    dirty = False

    # ── LLM providers — pick which to configure ──
    llm_indices = _select_providers("LLM Providers", DEFAULT_LLM_DEFS, provider_settings)
    if llm_indices:
        for i, idx in enumerate(llm_indices, 1):
            defn = DEFAULT_LLM_DEFS[idx]
            ptype = defn["provider_type"]
            existing = provider_settings.by_type(ptype)
            result = _configure_llm(defn, existing, i, len(llm_indices))
            if result is not None:
                provider_settings.upsert(result)
                dirty = True

    # ── Search providers — pick which to configure ──
    search_indices = _select_providers(
        "Search Providers", SEARCH_PROVIDER_DEFS, provider_settings
    )
    if search_indices:
        for idx in search_indices:
            defn = SEARCH_PROVIDER_DEFS[idx]
            ptype = defn["provider_type"]
            existing = provider_settings.by_type(ptype)
            result = _configure_search(defn, existing)
            if result is not None:
                provider_settings.upsert(result)
                dirty = True

    if not dirty:
        print(f"\n  {c(C.YELLOW, 'No providers configured. Exiting.')}\n")
        return

    _set_priorities(provider_settings, "llm")
    _set_priorities(provider_settings, "search")
    save_settings(provider_settings)
    print(f"\n  {c(C.GREEN, '✓')} Configuration saved to {c(C.BOLD, str(CONFIG_PATH))}")

    if _yn("Also write keys to .env file?", default=True):
        _update_dotenv(provider_settings)

    print(f"\n  {c(C.GREEN + C.BOLD, 'Done!')} Re-run anytime with:")
    print(f"    {c(C.CYAN, 'python -m argus onboard')}\n")
