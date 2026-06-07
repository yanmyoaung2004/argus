# Argus Architecture

## Overview

Argus is an autonomous research agent that decomposes a research query into steps,
executes them via specialized agents, and produces structured reports with cited
sources. It runs on a single-user local machine with a target cost of < $0.50
per research.

## Architecture Diagram

```
           ┌──────────────────┐
           │   FastAPI App    │
           │  (argus/app.py)  │
           └────┬───┬───┬────┘
                │   │   │
    POST /research  │   GET /{id}/report, /{id}/html
                │   │   │
           ┌────▼───▼───▼────────────┐
           │   Research Manager      │
           │  (orchestrator/manager) │
           └────┬────────────────────┘
                │ push steps
           ┌────▼──────────────┐
           │   Redis Streams    │
           │  • tasks           │
           │  • facts           │
           │  • progress        │
           │  • dlq             │
           └────┬──────────────┘
                │
     ┌──────────┼──────────┬──────────┐
     │          │          │          │
┌────▼───┐ ┌───▼────┐ ┌───▼───┐ ┌───▼──────┐
│Scout   │ │Deep-   │ │Verifi-│ │Synthesis │
│Agent   │ │Dive    │ │cation │ │Agent     │
└───┬────┘ │Agent   │ │Agent  │ │(contin.) │
    │      └───┬────┘ └───┬───┘ └────┬─────┘
    │          │          │          │
    └──────────┼──────────┼──────────┘
               │ emit facts
          ┌────▼──────────────┐
          │   KG Writer        │
          │ (knowledge_graph/  │
          │   writer.py)       │
          └────┬──────────────┘
               │ batch insert
          ┌────▼──────────────┐
          │   SQLite           │
          │  (entities, claims,│
          │   sources, edges)  │
          │  + FTS5 + vec0    │
          └────────────────────┘
               │
          ┌────▼──────────────┐
          │   Report Generator │
          │  Markdown + HTML   │
          │  + D3.js Graph     │
          └────────────────────┘
```

## Data Flow

1. **User** POSTs a query to `/research`
2. **ResearchManager** creates a `ResearchTask`, runs the `RuleBasedPlanner` to decompose
   the query into a DAG of `TaskStep` objects, and pushes each step to the `tasks`
   Redis stream
3. **Agent Workers** (scout, deep_dive, verification) consume from `tasks` via consumer
   groups, execute their step using the cost-aware LLM router, and emit extracted facts
   to the `facts` stream. Each agent type has its own consumer group for parallel execution.
4. **Synthesis Agent** continuously reads `facts` stream independently, resolves entities
   via fuzzy name matching + LLM, merges duplicates, and adds RELATED_TO edges between
   co-occurring entities
5. **KG Writer** consumes facts from `facts` stream, batch-inserts into SQLite (entities,
   claims, sources, edges tables, flush every 50ms or 100 facts), deduplicates by
   idempotency key
6. **Confidence Scoring** is recalculated per claim on every insert using the formula:
   `base(0.5) + source_boost(capped 0.3) + credibility_boost(avg*0.2) + recency_boost(0.1) - conflict_penalty(0.3)`
7. **Progress events** flow through `progress:{task_id}` stream → SSE streamer
   → HTTP client via `GET /{task_id}/status`
8. When all steps complete, **Report Generator** queries the KG and produces a report:
   Markdown (P1), JSON (P2), or interactive HTML with D3.js graph (P3)
9. Each agent writes **heartbeats** to Redis every 10s; `/health` aggregates and warns on stale agents

## Key Components

### LLM Layer (`argus/llm/`)
- **Providers**: OllamaProvider (free, local), GroqProvider (free tier),
  OpenRouterProvider (paid fallback), OpenAICompatibleProvider (generic)
- **Circuit Breaker**: Redis-backed per-provider state (CLOSED → OPEN → HALF_OPEN)
- **Router**: Task-type-aware fallback chain (e.g., planning: Ollama→Groq→OpenRouter)
- **Compressor**: Prompt compression for Ollama/Groq (removes filler, shortens instructions,
  compresses JSON examples — target 30-50% reduction)

### Tools Layer (`argus/services/tools/`)
- **Search**: DuckDuckGo (free, rate-limited 1 req/s) → SerpAPI (paid fallback)
- **Scraper**: httpx+BeautifulSoup (free) → Playwright (free, JS-rendered) → Firecrawl (paid)
- **Parser**: Format detection by extension/content-type (markdown, HTML, PDF, text)
- **Cost Tracker**: Redis-backed per-research accumulator with hard cap at $0.50
- **Credibility Scorer**: Domain authority, citation boosts, conflict penalties, post-research
  learning (sources with high-confidence claims get +0.05, conflicts get -0.05), user feedback

### Agents Layer (`argus/services/agents/`)
- **BaseAgent**: Abstract class with budget check, circuit breaker check, idempotent fact emission
- **ScoutAgent**: Query → search → deduplicate → emit Entity/Source facts. Uses Groq free tier
- **DeepDiveAgent**: Accepts URLs, scrapes content, batch LLM extraction (5-10/page), fallback
  to single extraction. Uses Ollama
- **VerificationAgent**: Groups claims by entity+attribute, sends conflicting pairs to LLM,
  emits ConflictEdge facts. Uses Groq free tier
- **SynthesisAgent**: Continuous process reading facts stream. Entity resolution via
  `SequenceMatcher` + LLM (auto-merge >0.85, LLM-decide 0.70-0.85, new <0.70). Periodically
  adds RELATED_TO edges for co-occurring entities (≥2 co-occurrences)

### Knowledge Graph (`argus/services/knowledge_graph/`)
- **Schema**: SQLite with WAL mode, FTS5 on claims, vec0 HNSW for entity/claim embeddings,
  indexed by task_id
- **Writer**: Redis stream consumer, batch flush (50ms/100 facts), dedup by idempotency key
- **Confidence**: Formula-based calculation with source count, credibility, recency, conflicts.
  Auto-recalculated on claim insert via `update_claim_confidence()`
- **Queries**: Recursive CTE for provenance chains, conflict detection, FTS5 search,
  ANN vector search via sqlite-vec

### Orchestrator (`argus/services/orchestrator/`)
- **ResearchManager**: Task lifecycle, plan decomposition, timeout monitoring, feedback handling
- **Planner**: Rule-based (regex patterns) + LLM fallback via CostAwareRouter
- **State Machine**: Planning→Investigating→Synthesizing→Reporting→Done
- **SSE Streamer**: Async generator reading `progress:{task_id}` Redis stream
- **Lifecycle**: FastAPI lifespan with signal handling, timeout checks, graceful shutdown
- **Agent Runner**: Consumer group reader with DLQ push on failure, progress event emission,
  per-agent-type dispatch

### Memory Layer (`argus/services/memory/`)
- **LLM Cache**: SHA256 keyed by model+prompt, TTL-based expiry (24h)
- **Source Cache**: URL-hash keyed markdown, TTL 7 days, user-markable for indefinite storage
- **Checkpoints**: Per-task per-step status for resume after crash
- **Vector Store**: sqlite-vec vec0 tables for entity/claim embeddings (384-dim HNSW),
  ANN similarity search, batch re-index

### Heartbeat (`argus/services/heartbeat.py`)
- Every agent writes `heartbeat:{agent_id}` key with 30s TTL, refreshes every 10s
- Health endpoint reads all heartbeats via Redis SCAN, reports stale agents as warning
- Agent IDs: `{agent_type}-worker-{unix_timestamp}`

### Dead-Letter Queue (`argus/services/dlq/`)
- Failed messages pushed to `dlq` stream with original payload, reason, timestamp
- DLQConsumer re-queues with exponential backoff (5s, 30s, 120s), archives after max 3 requeues
- Logs warning when DLQ length exceeds threshold (100)

### UI (`argus/ui/`)
- **MarkdownReportGenerator**: Entity tables, claims with confidence/sources, cost breakdown
- **HTMLReportGenerator**: Jinja2 template with D3.js force-directed graph visualization,
  expandable claim cards, source details, metrics dashboard
- **CLI Watcher**: `python -m argus.ui.watcher <task_id>` via httpx streaming
- **HTML Watcher**: Browser SSE client at `watcher.html`

## Deployment

### Docker Compose
```bash
docker-compose -f infra/docker-compose.yml up -d
```
- Two services: `redis` (7-alpine) and `app` (Python 3.13-slim)
- App depends on Redis health check
- Volumes for SQLite data persistence and Redis data

### Configuration
All settings via environment variables with `ARGUS_` prefix.
Copy `.env.example` to `.env` and uncomment as needed.
50+ config variables: LLM providers (keys, models, timeouts), Redis URL, SQLite path,
budget caps (default $0.50), cache TTLs, vector HNSW params, agent concurrency.

## Cost Management

| Item | Default (free) | Fallback (paid) | Hard cap |
|------|---------------|-----------------|----------|
| LLM calls | Ollama ($0) / Groq ($0) | OpenRouter (~$0.03/call) | $0.50/research |
| Search | DuckDuckGo ($0) | SerpAPI ($0.01/q) | $0.50/research |
| Scrape | httpx+BS4 ($0) / Playwright ($0) | Firecrawl ($0.003/page) | $0.50/research |

- **Soft cap at 60%** ($0.30): Log warning, continue
- **Hard cap at $0.50**: Raise BudgetExceededError, save partial results, report
- **CostTracker** tracks per-research in Redis with category breakdown
- **Prompt compression** reduces LLM tokens by 30-50%
- **Caching** (LLM, source, search) reduces duplicate calls by 30-70%

## Design Decisions

### Why SQLite over Neo4j?
Single-user local, zero infra cost, WAL mode handles concurrent reads + serialized
writes. Recursive CTEs on JSON columns handle provenance. sqlite-vec + FTS5 cover
vector and full-text search. Sufficient for up to 50K+ nodes.

### Why event-driven over direct writes?
Agents emit facts → KG Writer batch-inserts (50ms or 100 facts). Decouples producer
from storage. Enables replay after crash. Eliminates SQLite write contention from
multiple concurrent agents.

### Why cost-aware routing?
Different task types need different quality/cost. Discovery (Groq free, fast),
extraction (Ollama free, slower), conflict resolution (OpenRouter, better reasoning).
Automatic fallback without reconfiguration. 90% of calls hit free tier.

### Why DuckDuckGo + httpx over paid APIs?
Free, no API keys needed, good enough for research discovery (DuckDuckGo) and
80%+ of web pages (httpx+BeautifulSoup). Paid services (SerpAPI, Firecrawl) are
tertiary fallbacks only.
