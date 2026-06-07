# Argus — Implementation Plan

Target: autonomous research agent. Single-user local machine. < $0.50/research cost. Production quality from day one.

---

## Architecture overview

```
┌──────────────────────────┐      HTTP/SSE
│     FastAPI App          │◄───── (research queries + status)
│  (Research Manager)      │
└──────┬───────────────────┘
       │ POST /research
       ▼
┌──────────────────────────┐
│       Planner            │ ── decomposes query → DAG of task steps
│  (rules + LLM fallback)  │
└──────┬───────────────────┘
       │ push tasks
       ▼
┌──────────────────┐     ┌─────────────────────────────┐
│  Redis Streams   │────►│     Agent Workers            │
│  • tasks         │     │  (scout, deep_dive,          │
│  • facts         │     │   verification, synthesis)   │
│  • progress      │     │  • cost-aware LLM router     │
│  • dlq           │     │  • retry + circuit breaker   │
└──────────────────┘     │  • idempotency tokens        │
       │                 └──────────┬──────────────────┘
       │                            │ emit facts → facts stream
       │                            ▼
       │                 ┌──────────────────────────────┐
       │                 │      KG Writer (dedicated)    │
       │                 │  • reads facts stream         │
       │                 │  • batch inserts into SQLite  │
       │                 │  • deduplication on key       │
       │                 └──────────┬───────────────────┘
       │                            │
       │                 ┌──────────▼───────────────────┐
       │                 │   SQLite (Knowledge Graph)    │
       │                 │   + sqlite-vec (HNSW index)  │
       │                 │   + FTS5 (full-text search)  │
       │                 └──────────────────────────────┘
       │
       ▼
┌──────────────────────────┐
│    SSE Streamer          │ ← subscribes to progress stream
│  (incremental report     │   pushes partial results to frontend
│   chunks + final report) │
└──────────────────────────┘
```

### Data flow

1. User POSTs a research query to `/research`
2. Research Manager creates a task record, runs Planner
3. Planner decomposes query into a DAG of steps, pushes to `tasks` stream
4. Agent workers consume from `tasks`, execute their step
5. Agents use the cost-aware LLM router for all LLM calls
6. Agents emit extracted facts to the `facts` stream
7. KG Writer consumes `facts`, batch-inserts into SQLite
8. Agents emit progress events to `progress` stream
9. SSE Streamer consumes `progress`, pushes to frontend
10. When all steps complete, final report is assembled from KG snapshot

---

## Phase P1a: Core + Cost Foundation (Week 1)

Build the minimal end-to-end pipeline with all cost-control and reliability patterns baked in.

### Day 1-2: Project scaffold + shared layer

**Files to create:**

| File | Contents |
|------|----------|
| `pyproject.toml` | Project metadata, dependencies, tool config (ruff, mypy, pytest) |
| `.gitignore` | Python + SQLite + Redis + IDE ignores |
| `shared/models.py` | `ResearchTask`, `TaskStep`, `Fact`, `Source`, `Claim`, `Entity` — all Pydantic models |
| `shared/config.py` | Settings via pydantic-settings: LLM provider configs, Redis URL, SQLite path, cost caps, cache TTLs |
| `shared/logging.py` | Structured JSON logger via structlog or stdlib logging: task_id, step_id, component_id on every record |
| `shared/idempotency.py` | `IdempotencyKey` (UUID v7) generator; `IdempotencyChecker` (SQLite table of processed keys) |

**Dependencies** (`pyproject.toml`):
```
fastapi, uvicorn[standard]
redis[hiredis]
pydantic, pydantic-settings
httpx, beautifulsoup4, lxml
pymupdf
duckduckgo_search
ollama (Python client or httpx)
openai (for OpenAI-compatible endpoints like Groq/OpenRouter)
sqlite-vec
tenacity
pybreaker
structlog
pytest, pytest-asyncio, pytest-cov
ruff, mypy
```

**Test files to create:**
- `tests/unit/test_idempotency.py` — key generation is unique, dedup detection
- `tests/conftest.py` — pytest fixtures: temp SQLite DB, mock Redis, test config

**Verification:**
```
ruff check .
mypy .
pytest tests/unit/test_idempotency.py
```

### Day 3-4: LLM layer

**Files to create:**

| File | Contents |
|------|----------|
| `llm/schema.py` | Pydantic models for structured LLM output per task type: `PlanningOutput`, `ExtractionOutput`, `VerificationOutput`, `SynthesisOutput` |
| `llm/providers.py` | Abstract `LLMProvider` base class. Implementations: `OllamaProvider` (local, free), `GroqProvider` (free tier), `OpenRouterProvider` (cheap models). Each tracks tokens and estimated cost. |
| `llm/circuit_breaker.py` | `ProviderCircuitBreaker` — wraps pybreaker, per-provider state stored in Redis (key: `circuit:{provider_name}`), auto-resets after 30s. |
| `llm/router.py` | `CostAwareRouter` — task type → ordered list of providers. Tries primary, checks circuit breaker state, falls through on failure/rate-limit. Returns (response, provider_used, cost). |

**Key behaviors:**
- Every provider call wrapped in `tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))`
- Circuit breaker trips after 5 consecutive failures in 60s window
- Router logs: `task_id, step_id, provider, model, prompt_tokens, completion_tokens, cost, latency_ms`
- Cost tracker increments per-research accumulator in Redis

**Test files:**
- `tests/unit/test_circuit_breaker.py` — trip, half-open, reset
- `tests/unit/test_router.py` — fallback chain, cost tracking, rate-limit handling

### Day 5: Tool layer

**Files to create:**

| File | Contents |
|------|----------|
| `services/tools/search.py` | `WebSearch` class. Primary: `DuckDuckGoSearch` (free, rate-limited — 1 req/s). Fallback: `SerpAPISearch` (paid, configurable API key). Both return `List[SearchResult(url, title, snippet)]`. |
| `services/tools/scraper.py` | `WebScraper` class. Primary: `httpx` + `BeautifulSoup` (fast, free, handles most pages). Fallback 1: `PlaywrightScraper` (JS-rendered pages, headless Chromium). Fallback 2: `FirecrawlScraper` (paid API). Returns `ScrapedContent(url, markdown, metadata)`. Rate-limits to avoid being blocked. |
| `services/tools/parser.py` | `DocumentParser` — detects format by extension/content-type. Supports: markdown, HTML (via trafilatura or readability), PDF (via pymupdf). Returns clean markdown string. |
| `services/tools/cost_tracker.py` | `CostTracker` — Redis-backed accumulator per research task. Tracks: LLM cost, search API cost, scrape credits. Exposes `approve_call(cost) → bool` (rejects if over budget). |

**Key behaviors:**
- Search cache: `{query_hash → results}` with 1-hour TTL in SQLite
- Scrape cache: `{url_hash → markdown}` with 7-day TTL in SQLite
- Cost tracker checks cumulative cost before every external call; hard-caps at configured limit (default $0.50)
- All tools have retry + circuit breaker (wrapped via a shared `with_retry` decorator)

**Test files:**
- `tests/unit/test_cache.py` — cache hit, miss, expiry, hash collision
- `tests/unit/test_cost_tracker.py` — accumulation, cap enforcement, edge cases

### Day 6-7: Orchestrator + Scout Agent + KG Writer + Report

**Files to create:**

| File | Contents |
|------|----------|
| `services/orchestrator/routes.py` | FastAPI router: `POST /research` (accept query, return task_id), `GET /status/{task_id}` (SSE stream of progress), `GET /health` (component status) |
| `services/orchestrator/models.py` | Request/response Pydantic schemas: `ResearchRequest(query)`, `ResearchResponse(task_id, status)`, `ProgressEvent` |
| `services/orchestrator/manager.py` | `ResearchManager` — orchestrates lifecycle: create task → run planner → push tasks to queue → wait for completion → assemble report |
| `services/orchestrator/sse.py` | `SSEStreamer` — subscribes to `progress` Redis stream for a task_id, yields SSE events |
| `services/orchestrator/planner/rules.py` | Rule-based query decomposer: pattern-matches query type (competitive analysis, tech comparison, academic survey), returns list of task steps. Pure functions, no LLM. |
| `services/orchestrator/planner/llm_planner.py` | LLM-assisted planner: called when rules don't match. Sends query + examples to router, parses structured output into steps. |
| `services/orchestrator/planner/state_machine.py` | Simple state machine: `planning → investigating → synthesizing → reporting → done`. Each state has entry/exit actions. |
| `services/tools/credibility.py` | `SourceCredibilityScorer` — domain reputation heuristic, citation count tracking, consistency scoring. Updates credibility on KG write. |
| `services/agents/base.py` | `BaseAgent` — abstract class with: `run(task_step) → List[Fact]`. Mixes in: retry wrapper, circuit breaker check, idempotency key generation, cost tracker check. Every agent inherits this. |
| `services/agents/scout.py` | `ScoutAgent` — calls search tool per subquery, deduplicates results, emits `Entity` facts to `facts` stream. Uses Groq free tier (fast, good for discovery). |
| `services/knowledge_graph/schema.py` | SQLite schema DDL: `entities`, `claims`, `sources`, `edges` tables. WAL mode. FTS5 virtual table on `claims.content`. json columns for flexible attributes. |
| `services/knowledge_graph/writer.py` | `KGWriter` — reads `facts` stream, batch-inserts (flush every 50ms or 100 facts). Deduplicates by idempotency key. Updates confidence scores on insert. |
| `services/knowledge_graph/queries.py` | Read-only query functions: `get_entity`, `get_claims_for_entity`, `get_provenance_chain`, `find_conflicts`, `search_claims(query)`. Use recursive CTEs for provenance. |
| `services/memory/llm_cache.py` | `LLMCache` — sqlite-vec-based semantic cache. Embeds prompt, finds nearest neighbor by cosine similarity above threshold, returns cached response if hit. TTL 24h. |
| `services/memory/source_cache.py` | `SourceCache` — SQLite table `source_cache(url_hash, markdown, content_type, fetched_at)`. TTL 7 days. `get(url) → str|None`, `set(url, markdown)`. |
| `services/memory/checkpoints.py` | `CheckpointManager` — saves `{task_id → Set[completed_step_ids]}` to SQLite after each step. On resume, loads completed steps and skips them. |
| `ui/report_generator.py` | `MarkdownReportGenerator` — queries KG for all claims/entities/sources related to a task_id, generates Markdown with footnote citations. |

**Key behaviors:**
- Graceful shutdown: FastAPI `on_shutdown` event → `ResearchManager.shutdown()` → sends SIGTERM to agent processes → waits for current tasks (max 30s) → saves checkpoint → exits
- Health endpoint: checks Redis connectivity, SQLite file access, Ollama responsiveness. Returns 200 with JSON status or 503.
- SSE endpoint: `GET /status/{task_id}` returns `text/event-stream`. Events: `{"type": "step_start", "step_id": "..."}`, `{"type": "fact", "data": {...}}`, `{"type": "done", "report_url": "..."}`.
- Report generator: footnote format with confidence per source

**Test files:**
- `tests/unit/test_planner_rules.py` — each query pattern → correct step DAG
- `tests/unit/test_planner_llm.py` — mock LLM, verify parsing
- `tests/unit/test_confidence.py` — confidence calculation for all cases
- `tests/integration/test_scout_agent.py` — mock search, verify facts emitted
- `tests/integration/test_kg_writer.py` — mock facts stream, verify SQLite inserts, dedup
- `tests/integration/test_full_research.py` — end-to-end with mocks for external services

**Milestone checkpoint (end of Week 1):**
```
curl -X POST http://localhost:8000/research -H "Content-Type: application/json" \
  -d '{"query": "Top 10 YC companies by valuation"}'

→ task_id: "rs-abc123"

curl http://localhost:8000/status/rs-abc123
→ SSE stream: progress events → final Markdown report with citations
```

Runs entirely on local/free infrastructure. Total cost: $0.00.

---

## Phase P1b: Streaming + Robustness (Week 2)

**Goal:** Production-quality UX and operational resilience.

### Day 8: SSE streaming + lifecycle

- Wire SSE streamer to `progress` Redis stream consumer group
- Implement frontend watcher (CLI client or minimal HTML page using EventSource API)
- Research Manager: track `status` field (pending → running → completing → done → failed)
- Timeout: auto-fail research if no progress for 30 minutes

### Day 9: Budget enforcer + cost tracking

- `CostTracker`: complete implementation with Redis-backed counters
- Pre-call check: `approve_call(estimated_cost)` — if over budget, raise `BudgetExceeded`
- Research failure mode: if budget exceeded, save partial results, report "research stopped at $X of $Y budget"
- Cost report appended to final report: breakdown by provider, model, tool

### Day 10: Dead-letter queue

- Any message that exceeds max retries is pushed to `dlq` stream
- `DLQConsumer` — reads `dlq`, re-queues with exponential backoff (up to 3 re-queues), then logs and archives
- Alert: if `dlq` length exceeds threshold, log warning (future: notification)

### Day 11: Graceful shutdown

- `atexit` handler on all agent processes: flush pending facts, save checkpoint, exit
- FastAPI lifespan handler: on shutdown, wait for in-flight tasks (configurable timeout), save manager state
- Docker Compose: `docker-compose down` triggers graceful shutdown via SIGTERM → handled by app

### Day 12: Docker Compose

- `infra/Dockerfile`: multi-stage build (dev + prod), Python slim image
- `infra/docker-compose.yml`: app + Redis services. App depends on Redis. Volumes for SQLite data persistence.
- `.env.example` with all config variables documented

### Day 13-14: Testing + docs

- Unit test coverage for all P1b components: cost tracker, DLQ, checkpoint resume, graceful shutdown
- Integration test: kill agent mid-task → restart → verify resume
- Write `docs/architecture.md` — current state, diagrams, key decisions

**Milestone:** End-to-end with streaming, budget enforcement, crash recovery, and Docker Compose.

---

## Phase P2: Multi-Agent (Week 3)

**Goal:** Full agent swarm — scout, deep-dive, verification — running in parallel.

### Day 15-16: Deep-dive agent

| File | Contents |
|------|----------|
| `services/agents/deep_dive.py` | `DeepDiveAgent` — accepts Entity with URL, scrapes content, sends batched extraction prompts to LLM (5-10 sources per batch), emits `Claim` and `Source` facts. Uses Ollama (cheapest for bulk extraction). |

**Key behaviors:**
- Batch extraction: instead of 1 LLM call per source, group 5-10 similar sources and extract all facts in one call
- Fallback: if batch LLM call fails, fall back to single-source extraction
- Output: `Claim(text, confidence, source_url, extracted_at)`, `Source(url, title, content_hash)`

### Day 17-18: Verification agent

| File | Contents |
|----------|----------|
| `services/agents/verification.py` | `VerificationAgent` — reads `Claim` groups for the same entity, sends pairs to LLM for conflict detection, emits `ConfidenceUpdate` and `ConflictEdge` facts. Uses Groq free tier (fast, good for comparison). |

**Key behaviors:**
- Group claims by entity name (fuzzy-matched)
- For each claim, find overlapping claims (same entity, same attribute) via KG queries
- Send conflicting pairs to LLM: "Claim A says X, Claim B says Y. Are they contradictory?"
- Output: `ConfidenceUpdate(claim_id, new_score, reason)`, `ConflictEdge(claim_a, claim_b, type)`

### Day 19: Parallel execution

- Redis Streams consumer groups: each agent type has its own consumer group
- Multiple agent instances per type (controlled by `AGENT_CONCURRENCY` config)
- KG Writer scaled: one writer process, but can handle higher throughput with larger batches

### Day 20: Full idempotency

- ID generator uses UUID v7 (time-ordered, reduces index fragmentation)
- `IdempotencyChecker`: SQLite table `processed_keys(key_hash, created_at)`. Check before every insert. TTL cleanup runs hourly.
- All Redis stream messages include `idempotency_key` header

### Day 21: Integration tests

- `tests/integration/test_deep_dive.py` — mock scrape, verify claim facts
- `tests/integration/test_verification.py` — mock conflicting claims, verify conflict edges
- `tests/integration/test_full_research_parallel.py` — multi-step research, verify all agents executed, KG has expected nodes and edges

**Milestone:** All agent types operational. Parallel execution working. Idempotency prevents duplicates.

---

## Phase P3: Knowledge Graph + Synthesis (Week 4)

**Goal:** Continuous graph building, confidence scoring, interactive reports.

### Day 22-23: Synthesis agent

| File | Contents |
|------|----------|
| `services/agents/synthesis.py` | `SynthesisAgent` — reads `facts` stream continuously (not in response to a specific task), resolves entities (fuzzy name matching via vector similarity), merges duplicate entities, adds edges between related entities. Uses Ollama for entity resolution. |

**Key behaviors:**
- Entity resolution: embed entity name, find top-3 candidates via sqlite-vec HNSW index, if similarity > 0.85, merge. If 0.70-0.85, ask LLM to decide. If < 0.70, create new.
- Relation extraction: for co-occurring entities in claims, add `RELATED_TO` edges with weight proportional to co-occurrence count
- Continuous: runs as a long-lived process, processing facts as they arrive

### Day 24: Confidence scoring

- `services/knowledge_graph/confidence.py`: implement `calculate_confidence` from spec
- On every fact insert, KG Writer recalculates confidence for affected claims
- Confidence is stored in `claims.confidence` column, updated in batch

### Day 25: Source credibility

- `services/tools/credibility.py`: implement full scoring with learning
- On each research completion, update credibility: sources whose claims had high final confidence get +0.05, sources with conflicts get -0.05
- User feedback endpoint `POST /feedback/{source_id}` with rating (correct/incorrect/unsure)

### Day 26: HNSW index

- sqlite-vec supports HNSW via `vec0` virtual table
- Create index on entity embeddings and claim embeddings
- Migration: re-index after every 1000 new embeddings (or scheduled daily)

### Day 27-28: Interactive HTML report

| File | Contents |
|------|----------|
| `ui/report_generator.py` | Add `HTMLReportGenerator` — generates a self-contained HTML page with embedded D3.js graph visualization |
| `ui/templates/interactive_report.html` | Jinja2 template: executive summary, expandable section cards, D3.js force-directed graph, confidence color coding |
| `ui/static/graph_viz.js` | D3.js force-directed graph: nodes = entities/claims, edges = supports/conflicts, node color = confidence, edge width = weight |

**Key behaviors:**
- HTML report is a single file (all CSS/JS inlined) for easy sharing
- Graph visualization: zoom, pan, click node → show all claims for entity
- Sections expandable: click title → show claims → click claim → show sources

**Milestone:** Interactive HTML reports with graph visualization. Confidence scores update in real time.

---

## Phase P4: Polish + Performance (Week 5)

**Goal:** Optimize cost, performance, and operability.

### Day 29: Prompt compression

- `llm/compressor.py`: wrap LLMLingua or similar to compress system prompts before sending
- Measure compression ratio on sample prompts (target: 30-50% reduction)
- Only compress for Ollama and Groq (OpenRouter models may not support it)

### Day 30: Long-term source cache

- Extend `SourceCache` to support indefinite storage (user can mark sources as "keep")
- Cache pruning: background job deletes entries older than TTL (default 7 days)
- Cache stats endpoint: `GET /cache/stats` — hit rate, size, oldest entry

### Day 31: Heartbeats + liveness

- All agent processes write heartbeat to Redis: `heartbeat:{agent_id}` with TTL 30s, refresh every 10s
- Health endpoint aggregates: if any agent heartbeat is stale, return 200 with warning
- Log: stale heartbeats → WARN level

### Day 32-33: Performance tuning

- Profile a full research task:
  - Measure time per phase (planning, scout, deep-dive, verification, synthesis, report)
  - Measure LLM call latency per provider per task type
  - Measure cache hit rates (LLM, source, search)
  - Measure SQLite write throughput
- Adjust batch sizes, LLM concurrency, cache TTLs based on data
- Document findings in `docs/performance.md`

### Day 34-35: Documentation

- `docs/architecture.md`: updated with all components, data flow, deployment
- `docs/graph_schema.md`: complete SQLite schema, FTS5 config, vec0 index config
- `docs/agent_protocols.md`: Redis stream message formats, idempotency protocol, error handling

**Milestone:** All components documented. Performance baseline established. Caches tuned.

---

## Phase P5: Evaluation (Week 6-7)

**Goal:** Measure against targets. Run ablation studies. Generate comparison tables.

### Day 36-37: Benchmark datasets

| File | Contents |
|------|----------|
| `evaluation/datasets/market_research.json` | Query + expected entities + expected facts + expected sources |
| `evaluation/datasets/tech_comparison.json` | Query + expected comparison dimensions + expected claims |
| `evaluation/datasets/academic_survey.json` | Query + expected papers + expected citation relationships |

Each dataset entry:
```json
{
  "query": "...",
  "ground_truth": {
    "entities": ["EntityA", "EntityB"],
    "claims": [
      {"text": "...", "sources": ["url1", "url2"]}
    ],
    "min_sources": 20,
    "min_entities": 5,
    "max_hallucinations": 2
  }
}
```

### Day 38-39: Evaluation pipeline

| File | Contents |
|------|----------|
| `evaluation/pipeline.py` | `EvalPipeline` — for each dataset entry: run research (with mock external APIs for reproducibility), compare output to ground truth, compute metrics |
| `evaluation/metrics.py` | `MetricsCollector` — factual_accuracy, source_coverage, confidence_calibration_error, hallucination_rate, research_time_seconds, total_cost |

### Day 40: Ablation studies

Run all benchmarks with these variants:
1. Full system (all agents, caching, routing)
2. No verification agent (skip cross-checking)
3. No synthesis agent (no entity resolution, no relation extraction)
4. No LLM cache (disable semantic cache)
5. No cost-aware routing (always use Ollama)
6. No cost-aware routing (always use Groq)

### Day 41: Cost analysis

- Tabulate cost per variant per benchmark
- Calculate savings from: caching vs no-cache, routing vs always-Ollama, routing vs always-Groq
- Compare to target (< $0.50/research)

### Day 42-44: Analysis + reports

- Generate comparison tables for each metric × variant
- Identify which ablations have statistically significant impact
- Write `evaluation/reports/phase5_results.md` with full analysis
- Run final end-to-end test with real external APIs (no mocks)
- Measure actual time and cost for the demo research task

### Day 45: Final polish

- Fix any bugs found during evaluation
- Tune confidence calibration curve (adjust weights if calibration error > 10%)
- Update docs with final metrics

**Milestone:** "Argus finds 23% more sources than baseline RAG with 94% accuracy at $0.12/research."

---

## Cost management strategy

### Free tier default chain

```
LLM:      Ollama (free, local) → Groq free tier → OpenRouter cheap
Search:   DuckDuckGo (free) → SerpAPI (paid, $0.01/query)
Scrape:   httpx+BeautifulSoup (free) → Playwright (free, local) → Firecrawl (paid, $0.003/page)
```

### Expected cost breakdown per research (50 sources)

| Item | Primary (free) | Fallback | Worst case |
|------|---------------|----------|------------|
| LLM calls (~100) | $0.00 (Ollama) | $0.00 (Groq free, 30 req/min) | $0.30 (OpenRouter, $0.03/call) |
| Search (50 queries) | $0.00 (DuckDuckGo) | $0.50 (SerpAPI) | $0.50 |
| Scrape (50 pages) | $0.00 (httpx) | $0.00 (Playwright) | $0.15 (Firecrawl) |
| **Total** | **$0.00** | **$0.50** | **$0.95** |

### Cost-reduction tactics (ordered by impact)

1. **LLM response cache**: 50-70% cache hit rate → cuts LLM calls by 50-70%
2. **Prompt compression**: 20-50% token reduction → cuts LLM cost proportionally
3. **Source cache**: 30-50% hit rate across research tasks → cuts scrape + search cost
4. **Tiered routing**: 90% of calls hit free tier → 90% of calls cost $0
5. **Budget enforcer**: prevents runaway costs from any single research

### Budget enforcement

- Default hard cap: $0.50 per research (configurable)
- Soft cap at $0.30: emit warning log, continue
- Hard cap at $0.50: stop all LLM calls, save partial results, report "budget exceeded"
- Per-provider monthly cap: track in Redis, reset on config date
- Cost log: every external call logs cost to `cost_log` table for post-hoc analysis

---

## Testing strategy

### Unit tests (fast, no external deps)

| Area | Tests | Key mocks |
|------|-------|-----------|
| Idempotency | UUID uniqueness, dedup detection, TTL cleanup | SQLite in-memory |
| Circuit breaker | Trip, half-open, reset, state persistence | Mock Redis |
| LLM router | Provider selection, fallback chain, cost tracking, rate-limit handling | Mock provider responses |
| Confidence | All formulas, edge cases (0 sources, all conflicts, max confidence) | In-memory claims |
| Planner rules | Each query pattern → correct step DAG | None |
| Cost tracker | Accumulation, cap enforcement, multi-task isolation | Mock Redis |
| Cache | Hit, miss, expiry, hash collision | SQLite in-memory |

### Integration tests (Redis + SQLite, mocked external APIs)

| Test | What it verifies |
|------|-----------------|
| `test_scout_agent.py` | Agent reads task, calls mock search, emits correct facts to stream |
| `test_deep_dive.py` | Agent scrapes mock page, extracts facts, handles empty page |
| `test_verification.py` | Detects conflicting claims, emits conflict edges |
| `test_kg_writer.py` | Batch inserts, dedup by idempotency key, handles malformed facts |
| `test_full_research.py` | End-to-end: POST query → SSE events → Markdown report with citations |

### End-to-end test (real external APIs, slower)

- Run demo research task weekly
- Measure: time, cost, accuracy, hallucination rate
- Log to evaluation/reports/live_test_YYYY-MM-DD.json

### Test commands

```
# All unit tests
pytest tests/unit/ -v --cov=argus --cov-report=term-missing

# Specific integration test (requires Redis running)
pytest tests/integration/test_kg_writer.py -v

# Full research integration (mocked externals)
pytest tests/integration/test_full_research.py -v

# Lint + typecheck + test (run before every commit)
ruff check . && mypy . && pytest
```

---

## Key design decisions

### Why SQLite over Neo4j?

- Single-user local means no concurrent write contention from multiple users
- SQLite with WAL mode handles concurrent reads + serialized writes fine
- Recursive CTEs on JSON columns handle provenance chain traversal
- sqlite-vec + FTS5 cover vector search and full-text search
- Zero infrastructure cost, zero configuration
- If performance degrades past 50K nodes, then consider migration (but not before)

### Why event-driven over direct agent→KG writes?

- Agents are ephemeral and stateless — they emit facts and move on
- KG Writer can batch inserts (50ms or 100 facts) → higher throughput via SQLite transactions
- Write queue enables replay: if KG Writer crashes, facts are still in Redis
- Decouples producer schema from storage schema: agents emit generic facts, KG Writer maps to SQLite schema

### Why cost-aware routing instead of a single provider?

- Different task types have different quality/cost requirements
- Discovery tasks benefit from fast cheap models (Groq free)
- Extraction tasks benefit from slower but free models (Ollama)
- Conflict resolution needs better reasoning (OpenRouter cheap)
- Automatic fallback without manual reconfiguration

### Why DuckDuckGo over SerpAPI as default?

- Free, no API key needed, good enough for research discovery
- Rate-limited (1 req/s) but acceptable for 50 queries over 2-3 hours
- SerpAPI is a paid fallback only when DuckDuckGo results are insufficient

### Why httpx+BeautifulSoup over Firecrawl as default?

- Free, fast, handles 80%+ of pages
- Firecrawl costs $0.003/page — at 50 pages that's $0.15, 30% of budget
- Playwright fallback handles JS-heavy pages locally at no cost
- Firecrawl is tertiary fallback only
