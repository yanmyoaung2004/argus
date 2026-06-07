# Argus — User Manual

Autonomous research agent. Thinks in graphs, cites everything, shows its work.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Local Setup](#4-local-setup)
5. [Configuration](#5-configuration)
6. [Running the Server](#6-running-the-server)
7. [Making Research Queries](#7-making-research-queries)
8. [Watching Progress](#8-watching-progress)
9. [Getting Reports](#9-getting-reports)
10. [Feedback System](#10-feedback-system)
11. [System Health & Cache Stats](#11-system-health--cache-stats)
12. [Running Evaluations in Live Mode](#12-running-evaluations-in-live-mode)
13. [Docker Deployment](#13-docker-deployment)
14. [Advanced Configuration](#14-advanced-configuration)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Overview

Argus is an event-driven multi-agent research system. You give it a question, and it:

1. **Plans** the research strategy by classifying the query type
2. **Scouts** the web via DuckDuckGo for relevant sources
3. **Deep-dives** by scraping pages and extracting claims via LLM
4. **Verifies** by cross-checking conflicting claims across sources
5. **Synthesizes** by resolving duplicate entities and connecting related facts
6. **Reports** with a knowledge graph, confidence scores, and an interactive HTML report

All of this runs on free-tier infrastructure for under $0.50 per research query.

---

## 2. Architecture

```
                ┌─────────────┐
   HTTP POST    │  FastAPI    │
   ──────────►  │   Server    │
                └──────┬──────┘
                       │
               ┌───────▼───────┐
               │   Planner     │  (rule-based + LLM fallback)
               └───────┬───────┘
                       │ task steps
               ┌───────▼───────┐
               │ Redis Streams │
               │  • tasks      │
               │  • facts      │
               │  • progress   │
               │  • dlq        │
               └───────┬───────┘
          ┌────────────┼────────────────┐
          ▼            ▼                ▼
   ┌──────────┐ ┌──────────┐ ┌────────────────┐
   │  Scout   │ │Deep-Dive│ │  Verification   │
   │  Agent   │ │  Agent   │ │    Agent        │
   └──────────┘ └──────────┘ └────────────────┘
          │            │                │
          └────────────┼────────────────┘
                       │ facts stream
               ┌───────▼───────┐
               │  KG Writer    │  (batch inserts)
               └───────┬───────┘
                       │
               ┌───────▼───────┐
               │    SQLite     │
               │ Knowledge Graph│
               │ + FTS5 + vec0 │
               └───────┬───────┘
                       │
               ┌───────▼───────┐
               │  Report Gen   │
               │ Markdown/HTML │
               └───────────────┘
```

### Data flow

1. User sends a query to `POST /research`
2. Planner decomposes the query into a DAG of task steps
3. Steps are pushed to the `tasks` Redis stream
4. Agent workers consume from `tasks`, execute their step
5. Agents emit facts to the `facts` Redis stream
6. KG Writer consumes `facts`, batch-inserts into SQLite
7. Agents emit progress events to the `progress` stream
8. SSE streamer pushes progress to the frontend
9. When all steps complete, the report is assembled from the KG snapshot

---

## 3. Prerequisites

### Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16 GB |
| Disk | 10 GB free | 20 GB SSD |
| Network | Broadband | Broadband |

### Software

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python | >= 3.11, tested on 3.14.5 | Runtime |
| Redis | >= 7.0 | Message queue, cache, state |
| Docker | Latest (optional) | Containerized deployment |
| Ollama | Latest (recommended) | Free local LLM |
| Groq API key | Free (recommended) | Free cloud LLM tier |

### Required API Keys (optional but recommended)

| Service | Sign-up | Cost | When used |
|---------|---------|------|-----------|
| Groq | https://console.groq.com | Free (30 req/min) | Scout, verification tasks |
| OpenRouter | https://openrouter.ai | ~$0.0001-0.01/call | Paid LLM fallback |
| SerpAPI | https://serpapi.com | ~$0.01/query | Search fallback |
| Firecrawl | https://firecrawl.dev | ~$0.003/page | Scrape fallback |

**You do not need any API key to run Argus.** With Ollama installed locally and DuckDuckGo as the default search engine, every research query costs $0.00.

---

## 4. Local Setup

### 4.1 Clone the repository

```bash
git clone <repo-url> argus
cd argus
```

### 4.2 Create a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 4.3 Install dependencies

```bash
# Production dependencies
pip install -e .

# Include dev dependencies (for testing)
pip install -e ".[dev]"
```

Verify installation:
```bash
python -c "from argus.app import app; print('OK')"
```

### 4.4 Install and start Redis

**Option A: Docker (recommended)**
```bash
docker run -d --name argus-redis -p 6379:6379 redis:7-alpine
```

**Option B: Native install**
- Windows: Use WSL or the Microsoft archive at https://github.com/microsoftarchive/redis/releases
- macOS: `brew install redis && brew services start redis`
- Linux: `sudo apt install redis-server && sudo systemctl start redis`

Verify Redis is running:
```bash
redis-cli ping
# Should respond: PONG
```

### 4.5 Install and start Ollama (recommended)

```bash
# Download from https://ollama.com or:
# macOS: brew install ollama
# Linux: curl -fsSL https://ollama.com/install.sh | sh

# Pull a model
ollama pull llama3.2:3b

# Start the server
ollama serve
```

Verify Ollama:
```bash
curl http://localhost:11434/api/tags
# Should return a JSON list with your model
```

---

## 5. Configuration

### 5.1 Create .env file

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

### 5.2 Minimal configuration (Ollama + DuckDuckGo only)

For zero-cost operation with only local/free tools, your `.env` can be nearly empty:

```
ARGUS_GROQ_API_KEY=
```

That's it. Argus will use:
- **Ollama** at `http://localhost:11434` for all LLM calls
- **DuckDuckGo** for web search (free, rate-limited to 1 req/s)
- **httpx + BeautifulSoup** for web scraping (free)

### 5.3 Recommended configuration (add Groq free tier)

Adding a Groq API key speeds up scout and verification agents significantly:

```
ARGUS_GROQ_API_KEY=gsk_your_api_key_here
```

### 5.4 Full configuration with paid fallbacks

If you want all fallback options:

```ini
# === App ===
ARGUS_APP_HOST=0.0.0.0
ARGUS_APP_PORT=8000
ARGUS_APP_LOG_LEVEL=info

# === Redis ===
ARGUS_REDIS_URL=redis://localhost:6379/0

# === SQLite ===
ARGUS_SQLITE_PATH=C:\Users\you\.argus\knowledge.db    # Windows
# ARGUS_SQLITE_PATH=~/.argus/knowledge.db              # macOS/Linux

# === Ollama ===
ARGUS_OLLAMA_BASE_URL=http://localhost:11434
ARGUS_OLLAMA_MODEL=llama3.2:3b

# === Groq (free tier) ===
ARGUS_GROQ_API_KEY=gsk_your_api_key
ARGUS_GROQ_MODEL=llama-3.1-8b-instant

# === OpenRouter (paid fallback) ===
ARGUS_OPENROUTER_API_KEY=sk-or-v1-your-key
ARGUS_OPENROUTER_MODEL=mistralai/mixtral-8x7b-instruct

# === Budget ===
ARGUS_BUDGET_PER_RESEARCH=0.50

# === Agent ===
ARGUS_AGENT_CONCURRENCY=2
ARGUS_AGENT_HEARTBEAT_TTL=30
```

---

## 6. Running the Server

### 6.1 Start the server

```bash
uvicorn argus.app:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     (Press CTRL+C to quit)
```

The `--reload` flag auto-restarts on code changes (remove in production).

### 6.2 Verify the server is running

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "app": "argus",
  "version": "0.1.0",
  "uptime_seconds": 12.5,
  "agents_alive": 0,
  "agents_stale": 0,
  "agents": {}
}
```

### 6.3 API documentation

Once the server is running, open in your browser:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## 7. Making Research Queries

### 7.1 Using curl

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the latest advances in LLM agents?"}'
```

Response:
```json
{
  "task_id": "0192a1b0-c3d4-5e6f-7890-123456789abc",
  "status": "planning",
  "message": "Research task created: 0192a1b0-c3d4-5e6f-7890-123456789abc"
}
```

Save the `task_id` — you'll need it to watch progress and retrieve the report.

### 7.2 Using Python

```python
import httpx
import time

BASE_URL = "http://localhost:8000"

# Start research
resp = httpx.post(f"{BASE_URL}/research", json={"query": "Top Y Combinator companies by valuation"})
task = resp.json()
task_id = task["task_id"]
print(f"Task ID: {task_id}")
```

### 7.3 Using the Swagger UI

1. Open http://localhost:8000/docs
2. Click on `POST /research`
3. Click "Try it out"
4. Enter your query in the request body
5. Click "Execute"
6. Copy the `task_id` from the response

### 7.4 What happens after you submit

| Step | Typical duration | Description |
|------|-----------------|-------------|
| Planning | 1-3 seconds | Planner classifies query and creates a step DAG |
| Scout | 10-60 seconds | Web search + entity extraction |
| Deep-dive | 30-300 seconds | Page scraping + LLM claim extraction |
| Verification | 5-30 seconds | Cross-check conflicting claims |
| Synthesis | Continuous | Entity resolution and relation extraction |
| Report | 1-2 seconds | Generate final report from knowledge graph |

Total time: **1-5 minutes** for a typical query, depending on:
- Number of sources discovered (more = slower)
- LLM provider speed (Ollama local = slower, Groq = faster)
- Web scraping speed (depends on page sizes and network)

---

## 8. Watching Progress

### 8.1 CLI watcher (recommended)

Use the built-in SSE watcher to see progress in real time:

```bash
python -m argus.ui.watcher 0192a1b0-...

# Or with a custom URL:
python -m argus.ui.watcher 0192a1b0-... --url http://localhost:8000
```

Output looks like:
```json
{
  "event": "step_start",
  "data": {"step_id": 1, "agent": "scout", "goal": "Search for sources"}
}
---
{
  "event": "progress",
  "data": {"step_id": 1, "message": "Found 15 sources from DuckDuckGo"}
}
---
{
  "event": "step_complete",
  "data": {"step_id": 1, "facts_emitted": 12}
}
---
{
  "event": "done",
  "data": {"task_id": "0192a1b0-...", "report_url": "/research/0192a1b0-.../report"}
}
```

### 8.2 Browser SSE watcher

Open in your browser:
```
http://localhost:8000/static/watcher.html
```

Enter your `task_id` and click "Connect". You'll see events appear live.

### 8.3 Manual SSE stream

```bash
curl -N http://localhost:8000/research/0192a1b0-.../status
```

This streams `text/event-stream` format. Each event is:

```
event: progress
data: {"message": "Found 10 sources", "step_id": 1}

event: done
data: {"task_id": "0192a1b0-...", "report_url": "..."}
```

---

## 9. Getting Reports

### 9.1 Markdown report

```bash
curl http://localhost:8000/research/0192a1b0-.../report
```

Response:
```json
{
  "task_id": "0192a1b0-...",
  "report": "# Research Report\n\n## Entities\n- **OpenAI**\n  ..."
}
```

The Markdown report includes:
- Executive summary
- Entities table with descriptions and types
- Claims section with confidence scores and source citations
- Source metadata
- Cost breakdown

### 9.2 Interactive HTML report (recommended)

```bash
curl http://localhost:8000/research/0192a1b0-.../html
```

Save to a file and open in your browser:

```bash
curl http://localhost:8000/research/0192a1b0-.../html > report.html
start report.html     # Windows
open report.html      # macOS
```

The HTML report includes:
- **Metrics dashboard** — entity count, claim count, source count, total cost
- **Force-directed graph** — interactive D3.js visualization with:
  - **Blue/purple nodes**: Entities
  - **Green/yellow/red nodes**: Claims (color = confidence)
  - **Gray nodes**: Sources
  - **Edges**: Entity→Claim, Claim→Source relationships
  - **Zoom, pan, drag**: Navigate the graph
- **Expandable claim cards** — click to see full statement, confidence score, entity name, source URLs
- **Cost breakdown table** — by category (LLM, search, scrape)

### 9.3 Report via Python

```python
import httpx

BASE_URL = "http://localhost:8000"
task_id = "0192a1b0-..."

# Markdown
resp = httpx.get(f"{BASE_URL}/research/{task_id}/report")
print(resp.json()["report"])

# HTML (save to file)
resp = httpx.get(f"{BASE_URL}/research/{task_id}/html")
with open("report.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
```

---

## 10. Feedback System

Argus learns from user feedback. After reviewing a report, you can provide feedback on individual sources to improve future research quality.

### 10.1 Submit positive feedback

If a source was accurate and helpful:

```bash
curl -X POST http://localhost:8000/research/feedback/1 \
  -H "Content-Type: application/json" \
  -d '{"is_correct": true}'
```

This increases the source's credibility score by +0.15 (capped at 1.0).

### 10.2 Submit negative feedback

If a source was inaccurate or misleading:

```bash
curl -X POST http://localhost:8000/research/feedback/1 \
  -H "Content-Type: application/json" \
  -d '{"is_correct": false}'
```

This decreases the source's credibility score by -0.15 (floored at 0.0).

### 10.3 How feedback affects future research

- Sources with higher credibility scores boost confidence in their claims
- The confidence formula incorporates `avg(credibility_scores) * 0.2`
- Over time, the system learns which domains and sources are trustworthy

### 10.4 Finding source IDs

Source IDs appear in the report output. Look for lines like:

```
- Source ID: 1 | URL: https://example.com/article | Credibility: 0.85
```

---

## 11. System Health & Cache Stats

### 11.1 Health endpoint

```bash
curl http://localhost:8000/health
```

Returns:
```json
{
  "status": "ok",
  "app": "argus",
  "version": "0.1.0",
  "uptime_seconds": 3600.5,
  "agents_alive": 2,
  "agents_stale": 0,
  "agents": {
    "scout-1": {"alive": true, "ttl_remaining": 25, "last_seen": 1234567890.0, "age_seconds": 5.0},
    "deep-dive-1": {"alive": true, "ttl_remaining": 28, "last_seen": 1234567890.0, "age_seconds": 2.0}
  }
}
```

The `status` field is:
- `"ok"` — all agents are alive
- `"degraded"` — one or more agents have stale heartbeats

### 11.2 Cache stats

```bash
curl http://localhost:8000/cache/stats
```

Returns:
```json
{
  "status": "ok",
  "total_entries": 142,
  "kept_entries": 5,
  "hit_rate": 0.68,
  "hits": 340,
  "misses": 160,
  "total_size_bytes": 2457600,
  "ttl_seconds": 604800
}
```

Key metrics:
- **hit_rate**: Higher is better (target > 0.50). Indicates cache effectiveness.
- **kept_entries**: Sources you've marked for indefinite retention.
- **total_size_bytes**: Disk space used by cached source content.

---

## 12. Running Evaluations in Live Mode

The evaluation framework can run benchmarks against the live Argus server.

### 12.1 Make sure the server is running

```bash
uvicorn argus.app:app --host 0.0.0.0 --port 8000
```

### 12.2 Run a live benchmark

```bash
# Market research benchmark (live mode)
python -m evaluation.runner benchmark -m live

# Specific dataset
python -m evaluation.runner benchmark -m live \
  -d evaluation/datasets/tech_comparison.json

# All datasets
python -m evaluation.runner benchmark -m live \
  -d evaluation/datasets/market_research.json \
     evaluation/datasets/tech_comparison.json \
     evaluation/datasets/academic_survey.json
```

### 12.3 Run live ablation study

```bash
python -m evaluation.runner ablation -m live
```

### 12.4 Full evaluation suite

```bash
python -m evaluation.runner all -m live
```

Results are saved to `evaluation/reports/`:
- `benchmark_results.json` — raw metrics per dataset
- `ablation_results.json` — ablation comparison data
- `ablation_results.md` — formatted ablation table
- `phase5_results.md` — comprehensive evaluation report

---

## 13. Docker Deployment

### 13.1 Build and run with Docker Compose

```bash
cd infra

# Set your API keys
export ARGUS_GROQ_API_KEY=gsk_your_key

# Start all services
docker compose up --build

# Or run in background
docker compose up --build -d
```

This starts:
- **Redis 7** on port 6379
- **Argus app** on port 8000

### 13.2 Environment variables for Docker

Set these before running `docker compose up`:

```bash
export ARGUS_GROQ_API_KEY=gsk_your_key
export ARGUS_OPENROUTER_API_KEY=sk-or-v1-your-key
export ARGUS_OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Ollama needs `host.docker.internal` because it runs on the host, not in Docker.

### 13.3 Stopping

```bash
cd infra
docker compose down

# Remove volumes (deletes all data)
docker compose down -v
```

### 13.4 Viewing logs

```bash
docker compose logs -f app
docker compose logs -f redis
```

---

## 14. Advanced Configuration

### 14.1 All configuration options

Every setting can be set via environment variable with the `ARGUS_` prefix, or in `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `ARGUS_APP_HOST` | `0.0.0.0` | Server bind address |
| `ARGUS_APP_PORT` | `8000` | Server port |
| `ARGUS_APP_DEBUG` | `false` | Enable debug mode |
| `ARGUS_APP_LOG_LEVEL` | `info` | Log level (debug, info, warning, error) |
| `ARGUS_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `ARGUS_SQLITE_PATH` | `~/.argus/knowledge.db` | SQLite database path |
| `ARGUS_LLM_DEFAULT_MODEL` | `llama3.2:3b` | Default model name |
| `ARGUS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `ARGUS_OLLAMA_MODEL` | `llama3.2:3b` | Ollama model |
| `ARGUS_GROQ_API_KEY` | `` | Groq API key (free) |
| `ARGUS_GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model |
| `ARGUS_OPENROUTER_API_KEY` | `` | OpenRouter API key |
| `ARGUS_BUDGET_PER_RESEARCH` | `0.50` | Hard cost cap per query |
| `ARGUS_AGENT_CONCURRENCY` | `2` | Parallel agent workers |
| `ARGUS_AGENT_HEARTBEAT_TTL` | `30` | Heartbeat TTL in seconds |
| `ARGUS_REDIS_STREAM_MAXLEN` | `10000` | Max Redis stream length |
| `ARGUS_RESEARCH_IDLE_TIMEOUT_MINUTES` | `30` | Auto-fail idle research |
| `ARGUS_LLM_CACHE_TTL` | `86400` | LLM cache TTL (seconds) |
| `ARGUS_SOURCE_CACHE_TTL` | `604800` | Source cache TTL (seconds) |
| `ARGUS_DDG_RATE_LIMIT_PER_SECOND` | `1.0` | DuckDuckGo rate limit |

### 14.2 Configuring the LLM routing order

The routing table is defined in `argus/llm/router.py`. By default:

| Task Type | Primary | Fallback 1 | Fallback 2 |
|-----------|---------|------------|------------|
| Planning | Ollama | Groq | OpenRouter |
| Scout | Groq | Ollama | OpenRouter |
| Deep-dive | Ollama | Groq | OpenRouter |
| Verification | Groq | Ollama | OpenRouter |
| Synthesis | Ollama | Groq | OpenRouter |
| Conflict Resolution | Groq | OpenRouter | OpenAI-compatible |

To customize, edit the `ROUTING_TABLE` dict in `argus/llm/router.py`.

### 14.3 Configuring agent concurrency

Set `ARGUS_AGENT_CONCURRENCY` to control how many agent instances run in parallel:

```ini
ARGUS_AGENT_CONCURRENCY=4
```

Higher concurrency = faster research but more RAM usage.

### 14.4 Configuring the budget

```ini
# Hard cap per research
ARGUS_BUDGET_PER_RESEARCH=0.50

# Soft cap warning at 60% of hard cap (not configurable)
```

When the budget is exceeded, the research stops gracefully and saves partial results.

### 14.5 Cache management

**Mark a source for indefinite retention:**
This is done programmatically. The source cache stores content for 7 days by default. To keep sources longer, reduce the SQLite TTL or mark entries as `keep` via the API.

**Clear all caches:**
Delete the SQLite database file (default: `~/.argus/knowledge.db`) to clear all caches and the knowledge graph.

---

## 15. Troubleshooting

### 15.1 Server won't start

**Problem:** `ModuleNotFoundError: No module named 'argus'`

**Solution:** Make sure you're in the project root and the virtual environment is activated:

```bash
cd argus
.venv\Scripts\activate       # Windows
source .venv/bin/activate     # macOS/Linux
```

**Problem:** `redis.exceptions.ConnectionError`

**Solution:** Redis is not running. Start it:

```bash
docker run -d --name argus-redis -p 6379:6379 redis:7-alpine
```

### 15.2 Research fails immediately

**Problem:** `POST /research` returns `{"status": "failed", "error_message": "..."}`

**Possible causes:**

1. **Redis not running** — see above
2. **No LLM provider available** — check that Ollama is running or Groq API key is set:
   ```bash
   curl http://localhost:11434/api/tags          # Check Ollama
   ```
3. **Budget exceeded** — the cost tracker may think you've spent too much. Reset with:
   ```bash
   redis-cli DEL cost:research:{task_id}
   ```

### 15.3 Research is very slow

**Symptoms:** Report not generated after 10+ minutes

**Solutions:**

1. **Check if Ollama is running with a model:**
   ```bash
   curl http://localhost:11434/api/tags
   ```
   If no models are listed: `ollama pull llama3.2:3b`

2. **Increase agent concurrency:**
   ```ini
   ARGUS_AGENT_CONCURRENCY=4
   ```

3. **Add a Groq API key** — Groq is typically 5-10x faster than local Ollama:
   ```ini
   ARGUS_GROQ_API_KEY=gsk_your_key
   ```

4. **Check network** — if DuckDuckGo or web scraping is slow, check internet connectivity

5. **Restart Redis** — stale streams can cause issues:
   ```bash
   docker restart argus-redis
   ```

### 15.4 Report is empty or missing data

**Problem:** Report generated but has no entities or claims

**Possible causes:**

1. **Research was interrupted** — try again with a simpler query
2. **No sources found** — DuckDuckGo may have returned no results. Try a different query.
3. **LLM extraction failed** — check logs for LLM errors
4. **Budget was exceeded** — partial results may have been saved. Check the cost tracker.

### 15.5 SSE watcher shows no events

**Problem:** `python -m argus.ui.watcher <task_id>` shows no output

**Solutions:**

1. Verify the task ID is correct
2. Check that the server is running on port 8000
3. Check that the research is actually running (it may have completed already)
4. Try connecting with curl to see raw SSE:
   ```bash
   curl -N http://localhost:8000/research/<task_id>/status
   ```

### 15.6 Memory usage is high

**Problem:** Server uses too much RAM

**Solutions:**

1. Reduce agent concurrency:
   ```ini
   ARGUS_AGENT_CONCURRENCY=1
   ```
2. Reduce Redis stream maxlen:
   ```ini
   ARGUS_REDIS_STREAM_MAXLEN=1000
   ```
3. Reduce cache TTLs:
   ```ini
   ARGUS_SOURCE_CACHE_TTL=86400       # 1 day instead of 7
   ARGUS_LLM_CACHE_TTL=3600           # 1 hour instead of 24
   ```

### 15.7 Tests fail

**Problem:** `pytest` fails with import errors

**Solution:** Make sure dev dependencies are installed:

```bash
pip install -e ".[dev]"
```

And Redis tests require a running Redis instance:

```bash
docker run -d --name argus-redis -p 6379:6379 redis:7-alpine
```

### 15.8 "Budget exceeded" during research

**Problem:** Research stops with budget_exceeded status

**Solutions:**

1. Increase the budget cap:
   ```ini
   ARGUS_BUDGET_PER_RESEARCH=1.00
   ```
2. Use only free-tier providers (Ollama + DuckDuckGo + httpx) for zero cost
3. Check the cost breakdown in the report to see what's consuming budget

### 15.9 Checking logs

Always check the server logs first for error messages:

```bash
# Server stdout
uvicorn argus.app:app --reload --log-level debug

# Docker logs
docker compose -f infra/docker-compose.yml logs -f app
```

### 15.10 Getting help

If you encounter issues not covered here:

1. Check the project documentation:
   - `docs/architecture.md` — system architecture
   - `docs/graph_schema.md` — knowledge graph schema
   - `docs/agent_protocols.md` — Redis stream protocols
   - `docs/performance.md` — performance tuning

2. Open an issue at https://github.com/anomalyco/argus/issues

---

## Quick Reference Card

```bash
# Start everything
redis-server --daemonize yes
ollama serve &                          # or just `ollama serve`
uvicorn argus.app:app --reload

# Submit a research query
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the history of Y Combinator?"}'

# Watch progress
python -m argus.ui.watcher <task_id>

# Get markdown report
curl http://localhost:8000/research/<task_id>/report

# Get interactive HTML report
curl http://localhost:8000/research/<task_id>/html > report.html

# Submit feedback on a source
curl -X POST http://localhost:8000/research/feedback/1 \
  -H "Content-Type: application/json" \
  -d '{"is_correct": true}'

# Check system health
curl http://localhost:8000/health

# Cache stats
curl http://localhost:8000/cache/stats

# Run live benchmark
python -m evaluation.runner benchmark -m live

# Run all tests
pytest

# Lint and type check
ruff check .
mypy .
```
