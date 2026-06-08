from __future__ import annotations

import json
import re
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


_TAG_PATTERN = re.compile(r"\s*\((Free|Paid|Paid Fallback|Custom|Local|Web|AI Search)\)\s*")

def _strip_tags(name: str) -> str:
    return _TAG_PATTERN.sub("", name).strip()

def load_settings() -> ProviderSettings:
    if CONFIG_PATH.exists():
        raw = json.loads(CONFIG_PATH.read_text("utf-8"))
        settings = ProviderSettings(**raw)
        for p in settings.providers:
            p.display_name = _strip_tags(p.display_name)
        return settings
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
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    "google_ai_studio": [
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "litellm": [],
    "together_ai": [
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "mistralai/Mixtral-8x22B-Instruct-v0.1",
        "Qwen/Qwen2.5-72B-Instruct-Turbo",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-coder",
    ],
    "nvidia": [
        "meta/llama-3.1-8b-instruct",
        "meta/llama-3.1-70b-instruct",
        "meta/llama-3.1-405b-instruct",
        "mistralai/mistral-7b-instruct-v0.3",
        "mistralai/mixtral-8x22b-instruct-v0.1",
        "google/gemma-2-27b-it",
        "nvidia/nemotron-4-340b-instruct",
    ],
    "custom_openai": [],
    "openai_compatible": [],
}

DEFAULT_LLM_DEFS: list[dict[str, Any]] = [
    {
        "provider_type": "groq",
        "display_name": "Groq",
        "default_base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.1-8b-instant",
        "cost_input": 0.0,
        "cost_output": 0.0,
    },
    {
        "provider_type": "ollama",
        "display_name": "Ollama",
        "default_base_url": "http://localhost:11434",
        "default_model": "llama3.2:3b",
        "cost_input": 0.0,
        "cost_output": 0.0,
    },
    {
        "provider_type": "openrouter",
        "display_name": "OpenRouter",
        "default_base_url": "https://openrouter.ai/api/v1",
        "default_model": "mistralai/mixtral-8x7b-instruct",
        "cost_input": 0.27,
        "cost_output": 0.27,
    },
    {
        "provider_type": "openai",
        "display_name": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "cost_input": 2.50,
        "cost_output": 10.00,
    },
    {
        "provider_type": "anthropic",
        "display_name": "Anthropic",
        "default_base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-sonnet-20241022",
        "cost_input": 3.00,
        "cost_output": 15.00,
    },
    {
        "provider_type": "google_ai_studio",
        "display_name": "Google AI Studio",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-2.0-flash",
        "cost_input": 0.10,
        "cost_output": 0.40,
    },
    {
        "provider_type": "litellm",
        "display_name": "LiteLLM",
        "default_base_url": "http://localhost:4000",
        "default_model": "gpt-4o-mini",
        "cost_input": 0.0,
        "cost_output": 0.0,
    },
    {
        "provider_type": "together_ai",
        "display_name": "Together AI",
        "default_base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "cost_input": 0.88,
        "cost_output": 0.88,
    },
    {
        "provider_type": "deepseek",
        "display_name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "cost_input": 0.27,
        "cost_output": 1.10,
    },
    {
        "provider_type": "nvidia",
        "display_name": "NVIDIA",
        "default_base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "meta/llama-3.1-8b-instruct",
        "cost_input": 0.0,
        "cost_output": 0.0,
    },
    {
        "provider_type": "custom_openai",
        "display_name": "Custom (OpenAI-compatible)",
        "default_base_url": "",
        "default_model": "",
        "cost_input": 0.0,
        "cost_output": 0.0,
    },
    {
        "provider_type": "openai_compatible",
        "display_name": "OpenAI-Compatible",
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
        "display_name": "DuckDuckGo",
        "default_base_url": "",
        "needs_api_key": False,
        "cost_per_search": 0.0,
    },
    {
        "provider_type": "serpapi",
        "display_name": "SerpAPI",
        "default_base_url": "https://serpapi.com",
        "needs_api_key": True,
        "cost_per_search": 0.01,
    },
    {
        "provider_type": "firecrawl",
        "display_name": "Firecrawl",
        "default_base_url": "https://api.firecrawl.dev",
        "needs_api_key": True,
        "cost_per_search": 0.003,
    },
    {
        "provider_type": "tavily",
        "display_name": "Tavily",
        "default_base_url": "https://api.tavily.com",
        "needs_api_key": True,
        "cost_per_search": 0.01,
    },
]
