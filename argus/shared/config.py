from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "ARGUS_", "env_file": ".env", "env_file_encoding": "utf-8"}

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    app_log_level: str = "info"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # SQLite
    sqlite_path: str = str(Path.home() / ".argus" / "knowledge.db")
    sqlite_wal_mode: bool = True
    sqlite_cache_size: int = -64000  # 64MB

    # LLM providers
    llm_default_model: str = "llama3.2:3b"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: int = 120

    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: int = 60

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "mistralai/mixtral-8x7b-instruct"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: int = 60

    # OpenAI-compatible endpoint
    openai_compatible_api_key: str = ""
    openai_compatible_model: str = "gpt-4o-mini"
    openai_compatible_base_url: str = ""
    openai_compatible_timeout_seconds: int = 60

    # Budget
    budget_per_research: float = 0.50

    # Cache TTLs (seconds)
    llm_cache_ttl: int = 86400  # 24 hours
    source_cache_ttl: int = 604800  # 7 days
    search_cache_ttl: int = 3600  # 1 hour

    # Vector
    vector_embedding_model: str = "all-MiniLM-L6-v2"  # sqlite-vec built-in or custom
    vector_hnsw_ef_construction: int = 200
    vector_hnsw_m: int = 16

    # Agent concurrency
    agent_concurrency: int = 2
    agent_heartbeat_ttl: int = 30
    agent_shutdown_timeout_seconds: int = 30

    # Redis stream config
    redis_stream_maxlen: int = 10000
    redis_consumer_group: str = "argus-workers"

    # Research timeouts
    research_max_duration_minutes: int = 360
    research_idle_timeout_minutes: int = 30

    # LLM retry
    llm_retry_max_attempts: int = 3
    llm_retry_min_wait_seconds: float = 1.0
    llm_retry_max_wait_seconds: float = 10.0

    # Circuit breaker
    circuit_breaker_fail_max: int = 5
    circuit_breaker_reset_timeout_seconds: int = 30

    # SerpAPI (paid search fallback)
    serpapi_api_key: str = ""

    # Firecrawl (web scraping / search fallback)
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev"

    # DuckDuckGo rate limiting
    ddg_rate_limit_per_second: float = 1.0

    # Agent types by task
    agent_for_task: dict[str, str] = {
        "discover": "scout",
        "extract": "deep_dive",
        "verify": "verification",
        "synthesize": "synthesis",
    }

    # Task type by agent
    task_types_for_agent: dict[str, list[str]] = {
        "scout": ["discover"],
        "deep_dive": ["extract"],
        "verification": ["verify"],
        "synthesis": ["synthesize"],
    }


settings = Settings()
