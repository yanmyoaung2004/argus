from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from ddgs import DDGS
from tenacity import retry, stop_after_attempt, wait_exponential

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


class WebSearch:
    """Web search with DuckDuckGo as primary, SerpAPI and Firecrawl as fallbacks."""

    def __init__(self) -> None:
        self._duckduckgo = DuckDuckGoSearch()
        self._serpapi: SerpAPISearch | None = None
        self._firecrawl: FirecrawlSearch | None = None

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

    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        try:
            return self._duckduckgo.search(query, max_results=max_results)
        except Exception:
            pass

        if settings.serpapi_api_key:
            try:
                return self._get_serpapi().search(query, max_results=max_results)
            except Exception:
                pass

        if settings.firecrawl_api_key:
            try:
                return self._get_firecrawl().search(query, max_results=max_results)
            except Exception:
                pass

        return SearchResponse(
            results=[],
            metadata=SearchMetadata(
                provider="none",
                total_results=0,
                latency_ms=0,
            ),
        )
