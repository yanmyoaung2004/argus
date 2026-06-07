from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from ddgs import DDGS
from tenacity import retry, stop_after_attempt, wait_exponential

from argus.llm.provider_config import ProviderEntry
from argus.llm.provider_config import load_settings as load_provider_settings
from argus.shared.config import settings


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str


@dataclass
class SearchMetadata:
    provider: str
    total_results: int
    latency_ms: int
    cost: float = 0.0


@dataclass
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    metadata: SearchMetadata | None = None


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        ...


class DuckDuckGoSearch(SearchProvider):
    def __init__(self) -> None:
        self._last_request: float = 0.0
        self._rate_limit: float = settings.ddg_rate_limit_per_second

    def _wait_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < 1.0 / self._rate_limit:
            time.sleep((1.0 / self._rate_limit) - elapsed)

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        self._wait_rate_limit()
        start = time.monotonic()

        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=max_results))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        results = [
            SearchResult(
                url=r.get("href", ""),
                title=r.get("title", ""),
                snippet=r.get("body", ""),
            )
            for r in raw_results
        ]

        return SearchResponse(
            results=results,
            metadata=SearchMetadata(
                provider="duckduckgo",
                total_results=len(results),
                latency_ms=elapsed_ms,
                cost=0.0,
            ),
        )


class SerpAPISearch(SearchProvider):
    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or ""
        self._client = httpx.Client(timeout=15.0)

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        start = time.monotonic()

        response = self._client.get(
            self.BASE_URL,
            params={
                "q": query,
                "api_key": self._api_key,
                "num": max_results,
                "engine": "google",
            },
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        organic = data.get("organic_results", [])
        results = [
            SearchResult(
                url=r.get("link", ""),
                title=r.get("title", ""),
                snippet=r.get("snippet", ""),
            )
            for r in organic
        ]

        return SearchResponse(
            results=results,
            metadata=SearchMetadata(
                provider="serpapi",
                total_results=len(results),
                latency_ms=elapsed_ms,
                cost=0.01,
            ),
        )


class FirecrawlSearch(SearchProvider):
    """Firecrawl /v2/search — web search via Firecrawl API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key or ""
        self._base_url = (base_url or settings.firecrawl_base_url).rstrip("/") + "/v2"
        self._client = httpx.Client(timeout=15.0)

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        start = time.monotonic()

        response = self._client.post(
            f"{self._base_url}/search",
            json={"query": query, "limit": max_results},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        results: list[SearchResult] = []
        for item in data.get("data", []):
            results.append(
                SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("description", ""),
                )
            )

        return SearchResponse(
            results=results,
            metadata=SearchMetadata(
                provider="firecrawl",
                total_results=len(results),
                latency_ms=elapsed_ms,
                cost=0.003,
            ),
        )


class TavilySearch(SearchProvider):
    """Tavily AI-optimized search API."""

    BASE_URL = "https://api.tavily.com"

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key or ""
        self._base_url = (base_url or settings.tavily_base_url).rstrip("/")
        self._client = httpx.Client(timeout=15.0)

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        start = time.monotonic()

        response = self._client.post(
            f"{self._base_url}/search",
            json={
                "query": query,
                "api_key": self._api_key,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        raw_results = data.get("results", [])
        results = [
            SearchResult(
                url=r.get("url", ""),
                title=r.get("title", ""),
                snippet=r.get("content", ""),
            )
            for r in raw_results
        ]

        return SearchResponse(
            results=results,
            metadata=SearchMetadata(
                provider="tavily",
                total_results=len(results),
                latency_ms=elapsed_ms,
                cost=0.01,
            ),
        )


class WebSearch:
    """Web search with priority-based provider ordering from providers.json.

    Falls back to legacy env-var-based config when no search providers
    have been configured via ``onboard`` or ``search`` CLI.
    """

    def __init__(self) -> None:
        self._duckduckgo = DuckDuckGoSearch()
        self._serpapi: SerpAPISearch | None = None
        self._firecrawl: FirecrawlSearch | None = None
        self._tavily: TavilySearch | None = None
        self._profile_cache: dict[str, SearchProvider] = {}

    def _get_search_providers(self) -> list[ProviderEntry]:
        ps = load_provider_settings()
        enabled = ps.get_enabled("search")
        return sorted(enabled, key=lambda p: p.priority)

    def _build_provider(self, entry: ProviderEntry) -> SearchProvider | None:
        ptype = entry.provider_type
        cached = self._profile_cache.get(ptype)
        if cached is not None:
            return cached

        if ptype == "duckduckgo":
            inst: SearchProvider = DuckDuckGoSearch()
        elif ptype == "serpapi":
            inst = SerpAPISearch(api_key=entry.api_key or settings.serpapi_api_key)
        elif ptype == "firecrawl":
            inst = FirecrawlSearch(
                api_key=entry.api_key or settings.firecrawl_api_key,
                base_url=entry.base_url or settings.firecrawl_base_url,
            )
        elif ptype == "tavily":
            inst = TavilySearch(
                api_key=entry.api_key or settings.tavily_api_key,
                base_url=entry.base_url or settings.tavily_base_url,
            )
        else:
            return None

        self._profile_cache[ptype] = inst
        return inst

    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        providers = self._get_search_providers()
        if providers:
            for entry in providers:
                provider = self._build_provider(entry)
                if provider is None:
                    continue
                try:
                    return provider.search(query, max_results=max_results)
                except Exception:
                    continue
            return SearchResponse(
                results=[],
                metadata=SearchMetadata(provider="none", total_results=0, latency_ms=0),
            )

        # Legacy fallback: no search config saved yet, use env vars directly
        try:
            return self._duckduckgo.search(query, max_results=max_results)
        except Exception:
            pass

        if settings.serpapi_api_key:
            try:
                return self._serpapi.search(query, max_results=max_results)
            except Exception:
                pass

        if settings.firecrawl_api_key:
            try:
                return self._get_firecrawl().search(query, max_results=max_results)
            except Exception:
                pass

        if settings.tavily_api_key:
            try:
                return self._get_tavily().search(query, max_results=max_results)
            except Exception:
                pass

        return SearchResponse(
            results=[],
            metadata=SearchMetadata(provider="none", total_results=0, latency_ms=0),
        )

    def _get_serpapi(self) -> SerpAPISearch:
        if self._serpapi is None:
            self._serpapi = SerpAPISearch(api_key=settings.serpapi_api_key)
        return self._serpapi

    def _get_firecrawl(self) -> FirecrawlSearch:
        if self._firecrawl is None:
            self._firecrawl = FirecrawlSearch(
                api_key=settings.firecrawl_api_key,
                base_url=settings.firecrawl_base_url,
            )
        return self._firecrawl

    def _get_tavily(self) -> TavilySearch:
        if self._tavily is None:
            self._tavily = TavilySearch(
                api_key=settings.tavily_api_key,
                base_url=settings.tavily_base_url,
            )
        return self._tavily
