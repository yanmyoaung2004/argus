from __future__ import annotations

import time

import pytest

from argus.services.memory.source_cache import SourceCache


@pytest.fixture
def cache() -> SourceCache:
    return SourceCache(db_path=":memory:", ttl=3600)


class TestSourceCache:
    def test_get_miss_returns_none(self, cache: SourceCache) -> None:
        assert cache.get("https://example.com") is None

    def test_set_and_get(self, cache: SourceCache) -> None:
        cache.set("https://example.com", "markdown content")
        assert cache.get("https://example.com") == "markdown content"

    def test_expired_entry_returns_none(self, cache: SourceCache) -> None:
        cache._ttl = 0
        cache.set("https://example.com", "content")
        time.sleep(0.01)
        assert cache.get("https://example.com") is None

    def test_kept_entry_does_not_expire(self, cache: SourceCache) -> None:
        cache._ttl = 0
        cache.set("https://example.com", "content", keep=True)
        assert cache.get("https://example.com") == "content"

    def test_mark_keep(self, cache: SourceCache) -> None:
        cache.set("https://example.com", "content")
        assert cache.mark_keep("https://example.com") is True
        cache._ttl = 0
        assert cache.get("https://example.com") == "content"

    def test_mark_keep_missing(self, cache: SourceCache) -> None:
        assert cache.mark_keep("https://nonexistent.com") is False

    def test_clear_expired_skips_kept(self, cache: SourceCache) -> None:
        cache.set("https://a.com", "expired")
        cache.set("https://b.com", "kept", keep=True)
        cache._ttl = -1
        deleted = cache.clear_expired()
        assert deleted >= 1
        assert cache.get("https://b.com") == "kept"


class TestSourceCacheStats:
    def test_get_stats_returns_keys(self, cache: SourceCache) -> None:
        stats = cache.get_stats()
        assert "total_entries" in stats
        assert "hit_rate" in stats
        assert "ttl_seconds" in stats

    def test_stats_reflects_entries(self, cache: SourceCache) -> None:
        cache.set("https://a.com", "content a")
        cache.set("https://b.com", "content b", keep=True)
        stats = cache.get_stats()
        assert stats["total_entries"] == 2
        assert stats["kept_entries"] == 1

    def test_hit_rate_tracking(self, cache: SourceCache) -> None:
        cache.get("https://miss.com")
        cache.set("https://hit.com", "content")
        cache.get("https://hit.com")
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
