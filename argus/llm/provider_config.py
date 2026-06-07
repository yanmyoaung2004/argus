from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ProviderEntry(BaseModel):
    provider_type: str
    display_name: str
    category: str = "llm"
    enabled: bool = True
    base_url: str = ""
    api_key: str = ""
    selected_model: str = ""
    priority: int = 99
    cost_per_million_input: float = 0.0
    cost_per_million_output: float = 0.0


class ProviderSettings(BaseModel):
    providers: list[ProviderEntry] = Field(default_factory=list)

    def get_enabled(self, category: str | None = None) -> list[ProviderEntry]:
        filtered = self.providers
        if category:
            filtered = [p for p in filtered if p.category == category]
        return sorted(
            [p for p in filtered if p.enabled],
            key=lambda p: p.priority,
        )

    def by_type(self, provider_type: str) -> ProviderEntry | None:
        for p in self.providers:
            if p.provider_type == provider_type:
                return p
        return None

    def upsert(self, entry: ProviderEntry) -> None:
        for i, p in enumerate(self.providers):
            if p.provider_type == entry.provider_type:
                self.providers[i] = entry
                return
        self.providers.append(entry)


CONFIG_PATH = Path.home() / ".argus" / "providers.json"


def load_settings() -> ProviderSettings:
    if CONFIG_PATH.exists():
        raw = json.loads(CONFIG_PATH.read_text("utf-8"))
        return ProviderSettings(**raw)
    return ProviderSettings()


def save_settings(settings: ProviderSettings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        settings.model_dump_json(indent=2),
        encoding="utf-8",
    )


KNOWN_MODELS: dict[str, list[str]] = {
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ],
    "openrouter": [
        "mistralai/mixtral-8x7b-instruct",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "google/gemini-2.0-flash-lite-preview-02-05:free",
    ],
    "ollama": [],
    "openai_compatible": [],
}

DEFAULT_LLM_DEFS: list[dict[str, Any]] = [
    {
        "provider_type": "groq",
        "display_name": "Groq (Free)",
        "default_base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.1-8b-instant",
        "cost_input": 0.0,
        "cost_output": 0.0,
    },
    {
        "provider_type": "ollama",
        "display_name": "Ollama (Local)",
        "default_base_url": "http://localhost:11434",
        "default_model": "llama3.2:3b",
        "cost_input": 0.0,
        "cost_output": 0.0,
    },
    {
        "provider_type": "openrouter",
        "display_name": "OpenRouter (Paid Fallback)",
        "default_base_url": "https://openrouter.ai/api/v1",
        "default_model": "mistralai/mixtral-8x7b-instruct",
        "cost_input": 0.27,
        "cost_output": 0.27,
    },
    {
        "provider_type": "openai_compatible",
        "display_name": "OpenAI-Compatible (Custom)",
        "default_base_url": "",
        "default_model": "gpt-4o-mini",
        "cost_input": 0.15,
        "cost_output": 0.60,
    },
]

# Backward compat alias
DEFAULT_PROVIDER_DEFS = DEFAULT_LLM_DEFS

SEARCH_PROVIDER_DEFS: list[dict[str, Any]] = [
    {
        "provider_type": "duckduckgo",
        "display_name": "DuckDuckGo (Free)",
        "default_base_url": "",
        "needs_api_key": False,
        "cost_per_search": 0.0,
    },
    {
        "provider_type": "serpapi",
        "display_name": "SerpAPI (Paid)",
        "default_base_url": "https://serpapi.com",
        "needs_api_key": True,
        "cost_per_search": 0.01,
    },
    {
        "provider_type": "firecrawl",
        "display_name": "Firecrawl (Web)",
        "default_base_url": "https://api.firecrawl.dev",
        "needs_api_key": True,
        "cost_per_search": 0.003,
    },
]
