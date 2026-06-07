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


class WebSearch:
    """Web search with DuckDuckGo as primary and SerpAPI as fallback."""

    def __init__(self) -> None:
        self._duckduckgo = DuckDuckGoSearch()
        self._serpapi: SerpAPISearch | None = None

    def _get_serpapi(self) -> SerpAPISearch:
        if self._serpapi is None:
            self._serpapi = SerpAPISearch(api_key=settings.serpapi_api_key)
        return self._serpapi

    def search(self, query: str, max_results: int = 10) -> SearchResponse:
        try:
            return self._duckduckgo.search(query, max_results=max_results)
        except Exception:
            if settings.groq_api_key:
                try:
                    return self._get_serpapi().search(query, max_results=max_results)
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
