# Argus — AGENTS.md

Greenfield project. No code exists. Design docs are the source of truth.

## Sources (read in this order)

1. `project.md` — architecture, components, tech stack, folder layout, phases
2. `PLAN.md` — detailed week-by-week implementation plan with file-by-file guidance

## Key constraints

- **Single-user local machine** — no HA, no replicas, no K8s. Docker Compose is the deployment model.
- **< $0.50 per research** — free-first tools must be default. Paid services are fallbacks only.
- **Production quality from day one** — retry, circuit breaker, idempotency, graceful shutdown, structured logging. Do NOT skip these in P1.

## Architecture summary

```
Query → Planner → Redis Streams → Agents → Write Queue → KG Writer → SQLite
                                                              ↓
                                                     SSE Streamer → Frontend
```

- **Event-driven**: agents never write directly to the KG. They emit facts to a `facts` stream. A dedicated KG Writer process batch-inserts. This resolves SQLite write contention and enables replay.
- **Single KG writer**: only one process writes to SQLite. All others read. No concurrent-write problems.
- **Cost-aware LLM router**: every LLM call routes through a task-type-aware selector (see project.md for routing table).
- **Free-first tools**: DuckDuckGo search (not SerpAPI), httpx+BeautifulSoup (not Firecrawl), Ollama local (not paid LLMs).

## Tech stack

| Layer | Choice |
|-------|--------|
| Lang | Python >=3.11 |
| Web | FastAPI |
| Queue | Redis Streams |
| KG | SQLite + JSON columns + recursive CTEs (NO Neo4j) |
| Vector | sqlite-vec with HNSW index |
| FTS | SQLite FTS5 |
| LLM | Ollama > Groq free > OpenRouter cheap |
| Search | DuckDuckGo > SerpAPI |
| Scrape | httpx+BeautifulSoup > Playwright > Firecrawl |
| Test | pytest, pytest-asyncio, pytest-cov |
| Lint | ruff |
| Type | mypy --strict |
| Retry | tenacity |
| Circuit breaker | pybreaker |
| Infra | Docker Compose (Redis + app) |

## Cost-aware LLM routing order

```
Planning:      Ollama → Groq free → OpenRouter cheap
Scout:         Groq free → Ollama → OpenRouter cheap
Deep-dive:     Ollama → Groq free → OpenRouter cheap
Verification:  Groq free → Ollama → OpenRouter cheap
Synthesis:     Ollama → Groq free → OpenRouter cheap
Conflict res:  Groq free → OpenRouter cheap → OpenAI-compatible
```

## Implementation phases

| Phase | Timeline | Focus |
|-------|----------|-------|
| P1a | Week 1 | Core pipeline: scaffold, LLM router, retry, circuit breaker, cache, scout agent, planner, KG writer, Markdown reports |
| P1b | Week 2 | SSE streaming, budget enforcer, DLQ, graceful shutdown, Docker Compose, tests |
| P2 | Week 3 | Deep-dive, verification agents, parallel execution, idempotency, integration tests |
| P3 | Week 4 | Synthesis agent, confidence scoring, credibility, HNSW index, HTML reports with D3.js |
| P4 | Week 5 | Prompt compression, long-term cache, heartbeats, docs |
| P5 | Week 6-7 | Benchmarks, ablation studies, cost analysis ✅ |

## Key files by phase

### P1a-P4 (Weeks 1-5): Core pipeline, agents, graph, polish

```
pyproject.toml, .gitignore, README.md
shared/models.py, shared/config.py, shared/logging.py, shared/idempotency.py
llm/providers.py, llm/router.py, llm/circuit_breaker.py, llm/schema.py, llm/compressor.py
llm/prompts/{planning,extraction,synthesis}.txt
services/tools/search.py, services/tools/scraper.py, services/tools/parser.py
services/tools/cost_tracker.py, services/tools/credibility.py
services/agents/base.py, services/agents/scout.py, services/agents/deep_dive.py
services/agents/verification.py, services/agents/synthesis.py
services/knowledge_graph/schema.py, services/knowledge_graph/writer.py
services/knowledge_graph/queries.py, services/knowledge_graph/confidence.py
services/memory/llm_cache.py, services/memory/source_cache.py
services/memory/checkpoints.py, services/memory/vector_store.py
services/orchestrator/planner/rules.py, services/orchestrator/planner/llm_planner.py
services/orchestrator/planner/state_machine.py
services/orchestrator/manager.py, services/orchestrator/routes.py
services/orchestrator/sse.py, services/orchestrator/models.py
services/orchestrator/lifespan.py, services/orchestrator/timeout.py
services/orchestrator/agent_runner.py
services/dlq/consumer.py
services/heartbeat.py
ui/report_generator.py, ui/watcher.py, ui/templates/, ui/static/
infra/Dockerfile, infra/docker-compose.yml
.env.example
docs/architecture.md, docs/graph_schema.md, docs/agent_protocols.md, docs/performance.md
```

### P5 (Weeks 6-7): Evaluation

```
evaluation/datasets/market_research.json
evaluation/datasets/tech_comparison.json
evaluation/datasets/academic_survey.json
evaluation/metrics.py
evaluation/pipeline.py
evaluation/ablation.py
evaluation/runner.py
evaluation/report.py
```

## Conventions

- No CI yet, no pre-commit hooks — both need to be established
- Always run `ruff check . && mypy . && pytest` before considering work done
- Cost tracker must be wired into every LLM call and tool call from day one
- Every external call must have retry+circuit-breaker from day one
- Never write directly to SQLite from agents — always go through the write queue
- Idempotency key (UUID v7) on every message sent to any Redis stream
