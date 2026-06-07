# Argus — Autonomous Research Agent

Tagline: *Autonomous research agent that thinks in graphs, cites everything, and shows its work.*

---

## Core thesis

Current state:
- ChatGPT/Claude: single-turn, no memory, cites poorly
- RAG systems: retrieve → answer, no deep synthesis
- Research assistants: glorified search wrappers

The gap:

> No system conducts multi-day investigations, builds structured knowledge, tracks uncertainty, and provides full provenance for every claim.

Argus fills this:
- Accepts open-ended research questions
- Plans multi-step investigation strategies
- Builds knowledge graphs as it learns
- Tracks confidence per fact
- Generates audit-ready reports with full citation chains
- Runs entirely on local/free infrastructure with < $0.50 cost per research

---

## Example research task

User query:

> "Analyze the competitive landscape for AI-powered code review tools. I need: key players, pricing models, technical approaches, and market gaps."

Argus over 2-3 hours:

1. **Planning phase** (symbolic + LLM):
   - Break into subqueries: "who are the players?", "what do they charge?", "how do they work?"
   - Prioritize: competitors → pricing → tech → gaps
   - Estimate: ~50 sources needed

2. **Investigation phase** (event-driven multi-agent):
   - Scout agents: find candidate companies via free web search
   - Deep-dive agents: extract structured data from scraped pages
   - Verification agents: cross-check claims across sources
   - All agents emit events to a write queue; KG writer batch-inserts

3. **Synthesis phase** (continuous graph construction):
   - Build nodes: Company, PricingTier, TechStack
   - Build edges: Company -[offers]-> PricingTier
   - Detect conflicts and flag uncertainty

4. **Output phase** (streaming):
   - Partial results streamed via SSE as they complete
   - Final structured report with full citation chains
   - Every claim links to KG node → source documents

---

## High-level architecture

```
┌──────────────────────────────────────────────┐
│            FastAPI App (Research Manager)     │
│  POST /research · GET /status (SSE)          │
│  /health · graceful shutdown                 │
└──────┬───────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│              Planner (stateless)              │
│  • Symbolic decomposition                    │
│  • LLM-assisted when rules don't cover       │
│  • Output: DAG of task steps                 │
└──────┬───────────────────────────────────────┘
       │
       ▼
┌──────────────────┐     ┌──────────────────────────┐
│  Redis Streams   │────►│    Agent Workers          │
│  • task queue    │     │  (scout, deep_dive,       │
│  • write queue   │     │   verification, synthesis)│
│  • DLQ           │     │  • Cost-aware LLM router  │
└──────────────────┘     │  • Retry + circuit breaker│
       │                 │  • Idempotency tokens     │
       │                 └─────────┬────────────────┘
       │                           │ emit facts
       │                           ▼
       │                 ┌──────────────────────────┐
       │                 │     KG Writer (dedicated) │
       │                 │  • Batch inserts          │
       │                 │  • Deduplication          │
       │                 └──────────┬───────────────┘
       │                            │
       │                 ┌──────────▼───────────────┐
       │                 │   SQLite (Knowledge Graph)│
       │                 │  + sqlite-vec (vector)   │
       │                 │  + FTS5 (full-text)      │
       │                 └──────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│           SSE Streamer (incremental output)   │
│  • Progress events per completed task        │
│  • Partial claim sets as they land in KG     │
│  • Final report snapshot on completion       │
└──────────────────────────────────────────────┘
```

Key architectural decisions:
- **Event-driven**: agents emit facts to a write queue instead of writing directly to KG. This decouples producers from consumers, enables replay, and resolves SQLite write contention via batch inserts.
- **Single KG writer**: only one process writes to SQLite. All other processes read. This avoids the SQLite concurrent-write problem entirely.
- **Cost-aware LLM router**: every LLM call goes through a router that picks the cheapest adequate provider based on task type.
- **Free-first tools**: DuckDuckGo for search, httpx+BeautifulSoup for scraping. Paid services (SerpAPI, Firecrawl) are fallbacks only.

---

## Core components

### 1. Planning Engine

Responsibilities:
- Decompose research query into actionable subqueries
- Decide search strategy (breadth-first vs depth-first)
- Estimate completion (how many sources needed?)
- Dynamic re-planning (if initial results insufficient)

Tech:
- Symbolic planner: rule-based task decomposition
- LLM-assisted: when symbolic rules don't cover the query, ask local LLM (Ollama) to suggest strategies
- Output: DAG of task steps with dependency edges

```
{
  "task_id": "research_001",
  "query": "AI code review competitive landscape",
  "plan": {
    "steps": [
      { "id": 1, "type": "discover", "goal": "find top 10 players", "agent": "scout" },
      { "id": 2, "type": "extract", "goal": "get pricing for each", "agent": "deep_dive", "depends_on": [1] },
      { "id": 3, "type": "verify", "goal": "cross-check pricing claims", "agent": "verification", "depends_on": [2] }
    ],
    "estimated_sources": 50,
    "estimated_time_minutes": 120
  }
}
```

### 2. Agent Swarm

All agents are stateless processes that:
- Read tasks from Redis Streams
- Use the cost-aware LLM router
- Emit results to the write queue
- Have retry, circuit breaker, and idempotency built in

#### Scout Agent
- Role: Find candidate entities (companies, papers, people)
- Tools: DuckDuckGo (default), SerpAPI (fallback)
- Output: List of candidate entities with URLs

#### Deep-dive Agent
- Role: Extract structured data from sources
- Tools: httpx+BeautifulSoup (default), Playwright for JS pages, Firecrawl (fallback), pymupdf for PDFs
- Output: Structured facts + source links

#### Verification Agent
- Role: Cross-check facts across multiple sources
- Tools: LLM-based similarity comparison, conflict detection
- Output: Confidence scores + conflict flags

#### Synthesis Agent
- Role: Continuously build knowledge graph from emitted facts
- Tools: Entity resolution, relation extraction via local LLM
- Output: Graph nodes + edges inserted via KG writer

### 3. Event Pipeline

The backbone connecting all components:

| Stream | Producer | Consumer | Purpose |
|--------|----------|----------|---------|
| `tasks` | Planner | Agent workers | Distribute work |
| `facts` | Agent workers | KG Writer | Batch fact ingestion |
| `progress` | Agent workers | SSE Streamer | Live status updates |
| `dlq` | Any consumer | Manual inspection | Failed messages |

Properties:
- Redis Streams consumer groups for task distribution
- Idempotency key per message (UUID v7) to handle at-least-once delivery
- TTL on messages to prevent unbounded backlog

### 4. Knowledge Graph

Schema:

**Nodes:**
- Entity (name, type, description, confidence)
- Claim (statement, confidence, timestamp)
- Source (url, title, content_hash, credibility_score)

**Edges:**
- Entity -[SUPPORTS]-> Claim (weight: confidence)
- Claim -[CITED_BY]-> Source
- Entity -[RELATED_TO]-> Entity (type: competitor, partner, etc.)
- Claim -[CONFLICTS_WITH]-> Claim

**Tech: SQLite with JSON columns + recursive CTEs.**
- No Neo4j. SQLite is sufficient for single-user workloads up to 50K+ nodes.
- Recursive CTEs handle provenance chain traversal.
- sqlite-vec for vector similarity search (entity resolution, similar claims).
- SQLite FTS5 for full-text search across claims and sources.
- WAL mode enabled for concurrent reads during batch writes.

### 5. Uncertainty Tracking

Every claim has:
- Confidence score (0.0–1.0)
- Source count (supported by N sources)
- Recency (latest supporting evidence timestamp)
- Conflict flag (contradicted by other sources?)

Confidence calculation:
```
def calculate_confidence(claim):
    base = 0.5
    source_boost = min(0.3, len(claim.sources) * 0.1)
    credibility_boost = avg([s.credibility for s in claim.sources]) * 0.2
    recency_boost = 0.1 if claim.latest_source_age_days < 30 else 0
    conflict_penalty = -0.3 if claim.has_conflicts else 0
    return min(1.0, base + source_boost + credibility_boost + recency_boost + conflict_penalty)
```

### 6. Source Credibility Scoring

Heuristics:
- Domain reputation: .edu/.gov > company blogs > random sites
- Citation count: how often this source is cited in the graph
- Recency: newer = more credible for fast-moving topics
- Consistency: does this source agree with others?

Learning:
- Track which sources led to verified facts
- Demote sources that produced conflicting info
- User feedback: "wrong source" → lower credibility

### 7. Memory & Caching

| Cache | What | Storage | Eviction |
|-------|------|---------|----------|
| LLM response cache | (prompt_hash → response) | sqlite-vec (semantic) + JSON | TTL 24h |
| Source cache | (URL_hash → scraped markdown) | SQLite blob | TTL 7 days |
| Search cache | (query_hash → results) | SQLite JSON | TTL 1 hour |
| Vector index | claim/entity embeddings | sqlite-vec HNSW | On insert |

Checkpoint system:
- Save completed task IDs and KG state snapshot every N minutes
- Resume from checkpoint if interrupted
- Prevents re-fetching same URLs and re-processing completed tasks

### 8. Cost-Aware LLM Routing

```
Task type               Primary           Fallback 1        Fallback 2
────────────────────────────────────────────────────────────────────────
Planning/decomposition   Ollama (free)     Groq free tier    OpenRouter cheap
Scout/discovery         Groq free tier    Ollama (free)     OpenRouter cheap
Deep-dive extraction    Ollama (free)     Groq free tier    OpenRouter cheap
Verification/comparison Groq free tier    Ollama (free)     OpenRouter cheap
Synthesis/report gen    Ollama (free)     Groq free tier    OpenRouter cheap
Conflict resolution     Groq free tier    OpenRouter cheap  OpenAI-compatible
```

Each provider wrapper:
- Tracks cumulative token usage per research task
- Enforces per-research cost cap (default $0.50, configurable)
- Switches provider if primary is rate-limited, slow, or returning errors
- Logs per-call cost for cost attribution

### 9. Reliability Patterns

All built into the base agent and tool abstractions from day one:

| Pattern | Implementation | Trigger |
|---------|---------------|---------|
| Retry | `tenacity` with exponential backoff + jitter | Transient failures (timeout, 429, 503) |
| Circuit breaker | `pybreaker` — after 5 failures, fast-fail for 30s | Provider outage |
| Idempotency | UUID v7 task_id per message; KG writer deduplicates | At-least-once delivery duplicates |
| Dead-letter queue | Failed messages routed to `dlq` stream | Max retries exceeded |
| Graceful shutdown | SIGTERM handler drains in-flight agents, saves checkpoint | Process termination |
| Health check | `/health` endpoint reports status of all components | Monitoring / Docker |

### 10. Report Generation

**Format options:**

**Markdown with Citations** (P1):
```
## Key Players

- **GitHub Copilot** - Launched autofix feature in 2024[^1].
  Pricing: $10/mo for individuals[^2].

[^1]: [GitHub Blog](https://...") (Confidence: 0.95)
[^2]: [GitHub Pricing](https://...") (Confidence: 0.90)
```

**Structured JSON** (P2):
```json
{
  "query": "...",
  "generated_at": "...",
  "confidence": 0.87,
  "sections": [
    {
      "title": "Key Players",
      "claims": [
        {
          "text": "GitHub Copilot Autofix announced in 2024",
          "confidence": 0.95,
          "sources": ["https://..."],
          "reasoning_path": ["search_github", "extract_announcement", "verify_date"]
        }
      ]
    }
  ]
}
```

**Interactive HTML Report** (P3):
- Executive summary
- Knowledge graph visualization (D3.js or Cytoscape.js)
- Expandable sections with reasoning trees
- Confidence indicators (color-coded: green/yellow/red)
- Live SSE updates during research

---

## Tech stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python (>=3.11) | LLM/scraping ecosystem |
| Web framework | FastAPI | Async, SSE support, Pydantic |
| Queue | Redis Streams (via redis-py) | Lightweight, at-least-once, consumer groups |
| Knowledge graph | SQLite + JSON columns + recursive CTEs | Free, portable, sufficient for single-user |
| Vector search | sqlite-vec with HNSW index | Embedded, no extra service |
| Full-text search | SQLite FTS5 | Built into SQLite |
| LLM providers | Ollama (primary), Groq free tier (fallback 1), OpenRouter (fallback 2) | Cost-aware routing |
| Web search | DuckDuckGo (free, primary), SerpAPI (paid fallback) | Cost-optimized |
| Scraping | httpx + BeautifulSoup (default), Playwright (JS pages), Firecrawl (fallback) | Free-first |
| PDF parsing | pymupdf | Fast, accurate |
| LLM retry | tenacity | Industry standard |
| Circuit breaker | pybreaker | Lightweight |
| Task orchestration | Redis Streams consumer groups | Embedded in Redis, no extra broker |
| Reporting | Markdown (P1), JSON (P2), HTML/JS (P3) | Progressive complexity |
| Containerization | Docker Compose (Redis + app) | Local dev only |
| Testing | pytest + pytest-asyncio + pytest-cov | Standard Python |
| Linting | ruff | Fast, modern |
| Type checking | mypy (strict mode) | Catch type errors early |

---

## Folder structure

```
argus/
├── services/
│   ├── orchestrator/
│   │   ├── planner/
│   │   │   ├── rules.py              # Symbolic decomposition rules
│   │   │   ├── llm_planner.py        # LLM-assisted planning
│   │   │   └── state_machine.py      # Research phase tracking
│   │   ├── manager.py                # Research lifecycle management
│   │   ├── routes.py                 # FastAPI routes
│   │   ├── sse.py                    # SSE streaming endpoint
│   │   └── models.py                 # Pydantic schemas
│   │
│   ├── agents/
│   │   ├── base.py                   # Abstract agent + retry/circuit-breaker mixin
│   │   ├── scout.py                  # Discovery agent
│   │   ├── deep_dive.py              # Extraction agent
│   │   ├── verification.py           # Cross-checking agent
│   │   └── synthesis.py              # Graph-building agent
│   │
│   ├── knowledge_graph/
│   │   ├── schema.py                 # Node/edge definitions
│   │   ├── writer.py                 # Batch insert processor (reads facts queue)
│   │   ├── queries.py                # Read queries (CTEs, traversals)
│   │   ├── confidence.py             # Uncertainty calculations
│   │   └── provenance.py             # Citation chain tracking
│   │
│   ├── memory/
│   │   ├── vector_store.py           # sqlite-vec operations
│   │   ├── fts.py                    # SQLite FTS5 operations
│   │   ├── llm_cache.py              # LLM response cache (semantic)
│   │   ├── source_cache.py           # Scraped content cache
│   │   └── checkpoints.py            # State persistence
│   │
│   └── tools/
│       ├── search.py                 # Web search (DuckDuckGo → SerpAPI chain)
│       ├── scraper.py                # Content extraction (httpx → Playwright → Firecrawl)
│       ├── parser.py                 # PDF/HTML parsing
│       ├── credibility.py            # Source scoring
│       └── cost_tracker.py           # Per-research cost tracking
│
├── llm/
│   ├── providers.py                  # Provider wrappers (Ollama, Groq, OpenRouter)
│   ├── router.py                     # Cost-aware task-to-provider routing
│   ├── circuit_breaker.py            # Per-provider circuit breaker state
│   ├── prompts/
│   │   ├── planning.txt
│   │   ├── extraction.txt
│   │   └── synthesis.txt
│   └── schema.py                     # Structured output schema validation
│
├── evaluation/
│   ├── datasets/
│   │   ├── market_research.json
│   │   ├── tech_comparison.json
│   │   └── academic_survey.json
│   ├── pipeline.py                   # Automated evaluation runner
│   ├── metrics.py                    # Accuracy, coverage, cost tracking
│   └── reports/                      # Generated eval results
│
├── ui/
│   ├── report_generator.py           # Markdown/JSON/HTML export
│   ├── templates/
│   │   └── interactive_report.html   # HTML report template
│   └── static/
│       └── graph_viz.js              # D3.js visualization
│
├── shared/
│   ├── models.py                     # Shared data models
│   ├── logging.py                    # Structured logger
│   ├── config.py                     # Environment/settings management
│   └── idempotency.py                # UUID v7 generation + dedup check
│
├── infra/
│   ├── docker-compose.yml            # Redis + app
│   ├── Dockerfile                    # App container
│   └── redis/                        # Redis config
│
│   tests/
│   ├── unit/
│   │   ├── test_planner.py
│   │   ├── test_router.py
│   │   ├── test_cache.py
│   │   ├── test_circuit_breaker.py
│   │   ├── test_confidence.py
│   │   └── test_idempotency.py
│   ├── integration/
│   │   ├── test_scout_agent.py
│   │   ├── test_deep_dive.py
│   │   ├── test_verification.py
│   │   ├── test_kg_writer.py
│   │   └── test_full_research.py
│   └── conftest.py
│
└── docs/
    ├── architecture.md
    ├── graph_schema.md
    ├── agent_protocols.md
    └── evaluation_results.md
```

---

## Implementation phases

### P1a: Core + Cost Foundation (Week 1)

Goal: Runnable pipeline that can plan, search, extract, and report — with cost controls built in.

- Project scaffold: pyproject.toml, ruff, mypy, pytest, directory structure
- Shared: models, config, logging, idempotency utilities
- LLM layer: provider wrappers (Ollama, Groq, OpenRouter), cost-aware router, circuit breaker, retry, LLM response cache
- Tools: DuckDuckGo search, httpx+BeautifulSoup scraper, pymupdf parser
- Agents: base agent class with retry/circuit-breaker/idempotency mixin, scout agent
- Orchestrator: FastAPI app, /health endpoint, planner (rules + LLM), SSE skeleton, graceful shutdown handler
- Knowledge graph: SQLite schema, KG writer (reads facts stream, batch inserts), basic read queries
- Memory: source cache, checkpoint system
- Report: Markdown report generator
- Integration test: full "top 10 YC companies" research

**Milestone:** Can accept a research query, plan steps, execute scout, write facts to KG, generate Markdown report with citations. Total cost < $0.00 (all local/free).

### P1b: Streaming + Robustness (Week 2)

- SSE streaming of partial results
- Research manager with lifecycle tracking
- Budget enforcer (per-research cost cap)
- Dead-letter queue for failed agent tasks
- Graceful shutdown: SIGTERM → drain agents → save checkpoint → exit
- Docker Compose setup
- Unit tests for all P1a components
- Integration test suite

**Milestone:** End-to-end locally, with streaming progress, cost tracking, and crash recovery.

### P2: Multi-Agent (Week 3)

- Deep-dive agent: scraping + extraction with batch LLM calls (5-10 sources per prompt)
- Verification agent: cross-check claims, detect conflicts
- Parallel execution via Redis Streams consumer groups
- Idempotency enforcement in KG writer (dedup on insert)
- Integration test: complex multi-source research with verification

**Milestone:** Full agent swarm operational. Verification catches conflicts. All agents run in parallel.

### P3: Knowledge Graph + Synthesis (Week 4)

- Synthesis agent: continuous graph building (reads facts stream, resolves entities, merges edges)
- Confidence scoring for all claims
- Source credibility scoring
- HNSW index on sqlite-vec for fast vector search
- Provenance chain queries via recursive CTEs
- HTML report with D3.js graph visualization
- Frontend: interactive knowledge graph explorer

**Milestone:** Interactive HTML reports with graph visualization. Confidence scores per claim. Provenance chains work.

### P4: Polish + Performance (Week 5)

- Prompt compression (LLMLingua or similar) to reduce token usage
- Long-term source cache (7-day TTL)
- Agent heartbeats to Redis with TTL-based liveness detection
- Performance tuning: batch sizes, LLM concurrency, cache hit rates
- Documentation: architecture.md, graph_schema.md, agent_protocols.md

**Milestone:** Production-quality local system. All components documented. Caches effective.

### P5: Evaluation (Week 6-7)

- Build benchmark datasets (market research, tech comparison, academic survey)
- Automated evaluation pipeline
- Metrics: factual accuracy, source coverage, confidence calibration, hallucination rate, research time, cost per research
- Ablation studies: with/without verification, with/without KG, with/without caching
- Cost analysis report: actual vs budget, savings from caching/routing
- Generate comparison tables

**Milestone:** Measurable evidence that Argus meets targets. "Argus finds 23% more sources than baseline RAG with 94% accuracy at $0.12/research."

---

## Evaluation strategy

### Benchmark tasks:
1. Market research: "Top 10 YC companies by valuation in 2024"
   - Ground truth: manually verified list
   - Metrics: precision, recall, hallucination rate
2. Technical comparison: "React vs Vue vs Svelte: performance benchmarks"
   - Ground truth: published benchmark papers
   - Metrics: factual accuracy, source quality, confidence calibration
3. Academic survey: "Recent advances in transformer efficiency (2023-2024)"
   - Ground truth: arxiv.org search results
   - Metrics: coverage (% of key papers found), citation accuracy

### Metrics targets:

| Metric | Target | Measurement |
|--------|--------|-------------|
| Factual accuracy | >95% | Claims verified against ground truth |
| Source coverage | >80% | % of relevant sources discovered |
| Confidence calibration | <10% error | Does 0.9 confidence = 90% correct? |
| Hallucination rate | <2% | Claims with no source support |
| Avg research time | <2 hours | For medium-complexity tasks |
| Cost per research | <$0.50 | Total LLM + API costs |

### Ablation studies:
- With vs without verification agent: does cross-checking improve accuracy?
- With vs without KG: does graph synthesis help?
- Different planning strategies: breadth-first vs depth-first
- With vs without LLM cache: cost and time savings
- With vs without cost-aware routing: cost comparison

---

## What makes Argus interview-proof

1. **"How do you prevent hallucinations?"**
   → Every claim must link to source. Verification agent cross-checks. Confidence scoring surfaces uncertainty. All LLM calls use structured JSON output validation.

2. **"How do you handle contradictory sources?"**
   → Conflict detection in graph. Flag contradictions. Report both sides with confidence scores. Verification agent actively looks for disagreements.

3. **"How do you know when research is 'done'?"**
   → Convergence detection: new sources stop adding new facts. Confidence plateaus. User-defined thresholds (max time, max sources, budget cap).

4. **"How do you keep costs under $0.50?"**
   → Free-first infrastructure: Ollama local models, DuckDuckGo search, httpx scraping. Aggressive LLM response caching. Cost-aware router picks cheapest adequate provider. Per-research budget enforcer.

5. **"Show me the most complex research task you've solved."**
   → Interactive report with 50+ sources, 200+ facts, full provenance tree, confidence scores, and cost breakdown.

---

## Design constraints summary

- **Single-user local machine** (no HA, no replicas, no K8s)
- **< $0.50 per research** (free-first tools, aggressive caching, cost-aware routing)
- **Production quality from day one** (retry, circuit breaker, idempotency, structured logging, graceful shutdown)
- **SQLite permanently** (no Neo4j — sufficient for single-user up to 50K+ nodes)
- **Event-driven architecture** (agents emit events, dedicated KG writer batch-inserts)
