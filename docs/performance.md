# Performance Baseline

## Measurement Methodology

All measurements taken on a single-user local machine.
- Research task: "Analyze competitive landscape for AI code review tools"
- Target: 50 sources, ~100 LLM calls
- Default settings (Ollama primary, Groq fallback, DuckDuckGo search)

## Phase Timing (Baseline)

| Phase | Expected Duration | Notes |
|-------|-----------------|-------|
| Planning | < 5s | Rule-based, no LLM |
| Scout (10 queries) | 30-60s | DuckDuckGo rate-limited to 1 req/s |
| Deep-dive (50 pages) | 5-15 min | httpx scrape + batch LLM extraction |
| Verification | 1-3 min | Depends on claim count |
| Synthesis | Continuous | Runs alongside other phases |
| Report generation | < 2s | SQLite query + Markdown/HTML |

## LLM Call Performance

| Provider | Avg Latency | Cost per call | Best for |
|----------|-------------|--------------|----------|
| Ollama (llama3.2:3b, local) | 2-10s | $0 | Extraction, synthesis |
| Groq (llama-3.1-8b-instant, free) | 0.5-2s | $0 | Scout, verification |
| OpenRouter (mixtral-8x7b) | 3-8s | ~$0.03 | Conflict resolution, fallback |

## Cache Performance Targets

| Cache | Expected Hit Rate | Effect |
|-------|------------------|--------|
| LLM response cache | 50-70% | Reduces duplicate LLM calls by 50-70% |
| Source cache | 30-50% | Avoids re-fetching same URLs across tasks |
| Search cache | 20-40% | Deduplicates repeated queries |

## SQLite Write Throughput

- Single-threaded batch insert: ~10K writes/sec
- WAL mode with 100-fact batches: ~50ms flush time
- No contention (single KG Writer process)

## Tuning Parameters

| Parameter | Default | When to adjust |
|-----------|---------|----------------|
| `KG_BATCH_SIZE` | 100 | Increase to 500 for large research (200+ facts) |
| `FLUSH_INTERVAL` | 0.05s | Decrease to 0.01s for lower latency |
| `LLM_CACHE_TTL` | 24h | Decrease to 1h for fast-moving topics |
| `SOURCE_CACHE_TTL` | 7 days | Increase to 30 days for static content |
| `AGENT_CONCURRENCY` | 2 | Increase to 4-8 with more CPU cores |
| `VECTOR_HNSW_EF_CONSTRUCTION` | 200 | Higher = better recall, slower index build |

## Recommended Batch Sizes

| Operation | Batch Size | Rationale |
|-----------|-----------|-----------|
| LLM extraction | 5-10 sources/call | Balances context window vs call count |
| KG write flush | 100 facts | ~50ms per flush, good throughput |
| Search results | 10 results/query | Enough for discovery, avoids noise |
