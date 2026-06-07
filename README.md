# Argus — Autonomous Research Agent

> Thinks in graphs, cites everything, shows its work.

Argus is an event-driven, multi-agent research system. You give it a question, it plans a strategy, dispatches scout/deep-dive/verification agents via Redis Streams, builds a knowledge graph in SQLite, and produces an interactive HTML report with a D3.js force-directed graph — all for under $0.50 per research.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Redis 7+ (or Docker)
- [Ollama](https://ollama.com) (free, local LLM) — optional but recommended
- A Groq API key (free tier) — optional

### 1. Clone & install

```bash
git clone <repo-url> && cd argus
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -e ".[dev]"
```

### 2. Start Redis

Using Docker (recommended):

```bash
docker run -d --name argus-redis -p 6379:6379 redis:7-alpine
```

Or via Docker Compose:

```bash
docker compose -f infra/docker-compose.yml up redis -d
```

### 3. (Optional) Start Ollama

```bash
ollama pull llama3.2:3b
ollama serve
```

### 4. Configure

Copy `.env.example` to `.env` and adjust:

```bash
copy .env.example .env        # Windows
```

At minimum, set a Groq API key for the free LLM tier:

```
ARGUS_GROQ_API_KEY=gsk_...
```

All variables have safe defaults — only API keys for paid providers are required.

### 5. Run the server

**Important:** Start the app with the following command so that agent workers (scout, deep-dive, verification, synthesis, KG writer) run alongside the web server:

```bash
python -m argus
```

For development with hot-reload, run the web server and workers separately (two terminals):

```bash
# Terminal 1: worker processes
python -m argus --workers-only

# Terminal 2: web server with reload
uvicorn argus.app:app --reload --port 8001
```

Open http://localhost:8000/docs for the interactive Swagger UI.

---

## Usage

### Run a research query via API

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the latest advances in LLM agents?"}'
```

Response:

```json
{"task_id": "0192a1b0-...", "status": "planning", "message": "Research task created: 0192a1b0-..."}
```

### Watch progress via SSE

Using the CLI watcher:

```bash
python -m argus.ui.watcher 0192a1b0-...
```

Or open in a browser: `http://localhost:8000/static/watcher.html` and enter the task ID.

### Get the report

Markdown:

```bash
curl http://localhost:8000/research/0192a1b0-.../report
```

Interactive HTML (D3.js graph):

```bash
curl http://localhost:8000/research/0192a1b0-.../html
```

Open the HTML in a browser for the full interactive view with:
- Force-directed knowledge graph (entities + claims + sources)
- Expandable claim cards with confidence scores
- Source credibility breakdown
- Cost report

### Provide feedback

Improve source credibility for future research:

```bash
curl -X POST http://localhost:8000/research/feedback/1 \
  -H "Content-Type: application/json" \
  -d '{"is_correct": true}'
```

### Check system health

```bash
curl http://localhost:8000/health
```

Returns agent heartbeat status, uptime, stale agent detection.

### Cache stats

```bash
curl http://localhost:8000/cache/stats
```

Returns hit rate, total entries, kept entries, size, and expiry info.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/research` | Create a new research task |
| GET | `/research/{task_id}/status` | SSE stream of research progress |
| GET | `/research/{task_id}/report` | Markdown report |
| GET | `/research/{task_id}/html` | Interactive HTML report |
| POST | `/research/feedback/{source_id}` | Submit source credibility feedback |
| GET | `/health` | System health + agent heartbeats |
| GET | `/cache/stats` | Source cache statistics |

---

## Architecture

```
Query → Planner → Redis Streams → Agents → Write Queue → KG Writer → SQLite
                                                              ↓
                                                     SSE Streamer → Frontend
```

- **Planner** — classifies the query (competitive analysis, tech comparison, academic) and produces a step DAG (discover → extract → verify)
- **Scout Agent** — searches the web via DuckDuckGo, emits entities and source facts
- **Deep-Dive Agent** — scrapes pages via httpx/Playwright, batch-extracts claims via LLM
- **Verification Agent** — detects conflicting claims on the same entity+attribute, emits conflict edges
- **Synthesis Agent** — continuous entity resolution (fuzzy matching via SequenceMatcher + LLM), entity merging, RELATED_TO edge creation
- **KG Writer** — single-process batch consumer (50ms or 100 facts), writes to SQLite
- **Confidence Scoring** — auto-calculated on every claim: `base(0.5) + source_boost + credibility_boost + recency_boost - conflict_penalty`
- **Vector Store** — sqlite-vec HNSW index for ANN similarity search (384-dim embeddings)
- **Report Generator** — Markdown or interactive HTML with D3.js force-directed graph

### Cost-aware LLM routing

Every call routes through a task-type-aware selector with ordered fallback:

| Task Type | Primary | Fallback 1 | Fallback 2 |
|-----------|---------|------------|------------|
| Planning | Ollama | Groq | OpenRouter |
| Scout | Groq | Ollama | OpenRouter |
| Deep-dive | Ollama | Groq | OpenRouter |
| Verification | Groq | Ollama | OpenRouter |
| Synthesis | Ollama | Groq | OpenRouter |
| Conflict Resolution | Groq | OpenRouter | OpenAI-compatible |

Prompt compression (30-50% reduction) is automatically applied for Ollama and Groq calls.

---

## Project Structure

```
argus/
├── app.py                         # FastAPI app, health, cache stats endpoints
├── llm/
│   ├── providers.py               # Ollama, Groq, OpenRouter, OpenAI-compatible
│   ├── router.py                  # Cost-aware LLM router with fallback
│   ├── circuit_breaker.py         # Redis-backed per-provider circuit breaker
│   ├── compressor.py              # Prompt compressor (filler, instructions, JSON)
│   ├── schema.py                  # Structured output Pydantic models
│   └── prompts/                   # System prompt templates
├── services/
│   ├── agents/
│   │   ├── base.py                # Base agent (budget, circuit breaker, idempotency)
│   │   ├── scout.py               # Web search → entities/sources
│   │   ├── deep_dive.py           # Scrape → LLM extraction
│   │   ├── verification.py        # Conflict detection
│   │   └── synthesis.py           # Entity resolution + edge creation
│   ├── tools/
│   │   ├── search.py              # DuckDuckGo → SerpAPI
│   │   ├── scraper.py             # httpx → Playwright → Firecrawl
│   │   ├── parser.py              # Document parser (HTML, PDF, text)
│   │   ├── cost_tracker.py        # Budget enforcement via Redis
│   │   └── credibility.py         # Source credibility scoring + feedback
│   ├── orchestrator/
│   │   ├── manager.py             # Research lifecycle management
│   │   ├── agent_runner.py        # Redis Streams consumer group dispatcher
│   │   ├── routes.py              # FastAPI routes
│   │   ├── sse.py                 # SSE streamer
│   │   ├── lifespan.py            # App lifespan + graceful shutdown
│   │   ├── timeout.py             # Idle timeout monitor
│   │   └── planner/               # Rule-based + LLM planner
│   ├── knowledge_graph/
│   │   ├── schema.py              # SQLite DDL (WAL, FTS5, vec0)
│   │   ├── writer.py              # Batch KG writer (facts stream consumer)
│   │   ├── confidence.py          # Confidence scoring + recalculation
│   │   └── queries.py             # Provenance, conflicts, FTS5 search
│   ├── memory/
│   │   ├── llm_cache.py           # LLM response cache (SHA256 keyed)
│   │   ├── source_cache.py        # Source cache with keep/prune/stats
│   │   ├── vector_store.py        # sqlite-vec HNSW ANN index
│   │   └── checkpoints.py         # Per-step checkpoint persistence
│   ├── dlq/
│   │   └── consumer.py            # Dead-letter queue with re-queue backoff
│   └── heartbeat.py               # Agent heartbeat writer + alive checker
├── ui/
│   ├── report_generator.py        # Markdown + HTML report generators
│   ├── watcher.py                 # CLI SSE watcher
│   ├── templates/                 # Jinja2 HTML report template
│   └── static/                    # D3.js graph viz, browser SSE watcher
├── shared/
│   ├── config.py                  # pydantic-settings (50+ params)
│   ├── models.py                  # All data models
│   ├── logging.py                 # structlog setup
│   └── idempotency.py             # UUID v7 + SQLite dedup
infra/
├── Dockerfile                     # Multi-stage production build
└── docker-compose.yml             # Redis + app
docs/
├── architecture.md                # Full architecture with diagrams
├── graph_schema.md                # SQLite schema documentation
├── agent_protocols.md             # Redis stream protocols, idempotency
└── performance.md                 # Performance tuning guide
```

---

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=argus

# Run specific test file
pytest tests/unit/test_compressor.py -v

# Run integration tests
pytest tests/integration/ -v
```

Current test count: **164 tests** (158 unit + 6 integration)

### Lint & type check

```bash
ruff check .
mypy .
```

---

## Deployment

### Docker Compose (recommended)

```bash
# Set required API keys
export ARGUS_GROQ_API_KEY=gsk_...

# Start all services
docker compose -f infra/docker-compose.yml up --build

# Or run in background
docker compose -f infra/docker-compose.yml up --build -d
```

The app is available at `http://localhost:8000`.

### Configuration

All configuration is via environment variables with prefix `ARGUS_`. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `ARGUS_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `ARGUS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `ARGUS_GROQ_API_KEY` | — | Groq API key |
| `ARGUS_BUDGET_PER_RESEARCH` | `0.50` | Hard cost cap per query |
| `ARGUS_AGENT_CONCURRENCY` | `2` | Parallel agent workers |

See `.env.example` for the full list.

---

## Cost

Argus is designed to run for **under $0.50 per research query**:

| Service | Cost | When used |
|---------|------|-----------|
| Ollama (local) | Free | Default LLM |
| DuckDuckGo | Free | Default search |
| httpx + BeautifulSoup | Free | Default scrape |
| Groq free tier | Free | Scout, verification tasks |
| SQLite + sqlite-vec | Free | Knowledge graph + vector store |
| SerpAPI | ~$0.01/query | Fallback if DDG fails |
| OpenRouter | ~$0.0001-0.01/call | Paid LLM fallback |
| Firecrawl | ~$0.003/page | Tertiary scrape fallback |

The cost tracker enforces the hard cap at runtime and logs a warning at 60%.

---

## Docs

- [`docs/architecture.md`](docs/architecture.md) — Full system architecture
- [`docs/graph_schema.md`](docs/graph_schema.md) — Knowledge graph schema
- [`docs/agent_protocols.md`](docs/agent_protocols.md) — Redis stream protocols
- [`docs/performance.md`](docs/performance.md) — Performance tuning
- [`project.md`](project.md) — High-level design doc
- [`PLAN.md`](PLAN.md) — Implementation plan
