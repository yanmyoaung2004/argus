# Argus User Manual

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Start Redis (Docker)
docker run -d --name argus-redis -p 6379:6379 redis:7-alpine

# Run the setup wizard
python -m argus onboard

# Launch the server
python -m argus
```

Open http://localhost:8000/docs

---

## CLI Onboarding Wizard

The `onboard` command is the recommended way to configure Argus:

```bash
python -m argus onboard
```

It walks you through all providers interactively, validates API keys immediately, and saves the configuration to `~/.argus/providers.json`.

### LLM Providers

| Provider | Cost | Key Required | Notes |
|----------|------|-------------|-------|
| **Groq** | Free | Yes | Primary free LLM. Model: `llama-3.1-8b-instant` |
| **Ollama** | Free | No | Local LLM. Requires `ollama serve` running |
| **OpenRouter** | ~$0.0001–0.01 | Yes | Paid fallback with free models available |
| **OpenAI-Compatible** | Varies | Yes | Custom endpoint (e.g., Lightning AI, Azure) |

Each provider prompts for:
- **Enable?** — toggle on/off without losing saved key
- **Base URL** — defaults provided, can be customized
- **API Key** — masked input, tested immediately
- **Model** — fetched from the provider's API; if that fails, a known list is shown

If a key is invalid, you get 3 retry attempts before the provider is skipped.

### Search Providers

| Provider | Cost | Key Required | Notes |
|----------|------|-------------|-------|
| **DuckDuckGo** | Free | No | Always available, no setup needed |
| **SerpAPI** | ~$0.01/query | Yes | Google search results API |
| **Firecrawl** | ~$0.003/page | Yes | Web scraping + search (v2 API) |

Search providers are configured the same way — enable, enter API key, test connection.

### Priority Ordering

After configuring providers, the wizard asks you to set priority for LLM and search providers separately:

- **Priority 1** = primary (tried first)
- Priority increases = tried later (fallback)
- Only enabled providers with valid keys participate

### .env Update

At the end, the wizard offers to write your API keys and model selections into `.env`:

```
ARGUS_GROQ_API_KEY=gsk_...
ARGUS_GROQ_MODEL=llama-3.1-8b-instant
ARGUS_SERPAPI_API_KEY=...
ARGUS_FIRECRAWL_API_KEY=...
```

You can skip this if you prefer to manage `.env` manually.

---

## Running the Server

### Standard mode (workers + web server)

```bash
python -m argus
```

Starts:
- 4 agent workers (scout, deep-dive, verification, synthesis)
- KG writer (batch consumer)
- FastAPI web server on port 8000

### Workers only (no web UI)

```bash
python -m argus --workers-only
```

### Web server only (for development with hot-reload)

```bash
uvicorn argus.app:app --reload --port 8001
```

Run `python -m argus --workers-only` in a separate terminal alongside this.

---

## Submitting a Research Query

### From the command line (recommended)

The server must be running (`python -m argus` in another terminal):

```bash
# Defaults: 50 max sources, 30 min time limit
python -m argus research "What are the latest advances in LLM agents?"

# Custom limits
python -m argus research "AI coding tools comparison" --max-sources 33 --time-limit 333
```

The CLI:
1. Submits the query to the running server
2. Watches progress live via SSE
3. Fetches the HTML report on completion
4. Saves to `report_{slug}_{task_id}.html`
5. Opens it in your browser

### Via API (curl)

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the latest advances in LLM agents?"}'
```

Returns a `task_id` (UUID v7). Use this to track progress and fetch reports.

### Watch progress

```bash
python -m argus.ui.watcher <task_id>
```

Or open `http://localhost:8000/static/watcher.html` in a browser and enter the task ID.

### Get the report

```bash
# Markdown
curl http://localhost:8000/research/<task_id>/report

# Interactive HTML (with knowledge graph)
curl http://localhost:8000/research/<task_id>/html
```

The HTML report features:
- Premium dark-themed layout
- Force-directed knowledge graph (entities, claims, sources)
- Expandable claim cards with confidence scores
- Source credibility breakdown
- Cost report

### Track tasks & status

List all research tasks with their current status, query, and cost:

```bash
python -m argus list
```

Example output:
```
  Task ID                                  Status               Query                                               Cost
  ──────────────────────────────────────── ──────────────────── ────────────────────────────────────────────────── ──────────
  0192a1b0-1234-5678-9abc-def012345678     done                 What are the latest advances in LLM agents?       $0.0023
  0192a1b0-8765-4321-0fed-cba987654321     running              AI coding tools comparison 2026                    $0.0011
```

Check detailed status of a specific task, including step progress:

```bash
python -m argus status <task_id>
```

Example output:
```
  Task ID:     0192a1b0-1234-5678-9abc-def012345678
  Query:       What are the latest advances in LLM agents?
  Status:      done
  Max sources: 50
  Max time:    30 min
  Created:     2026-06-07T12:00:00
  Completed:   2026-06-07T12:03:45
  Cost:        $0.0023

  Steps (3):
    ✅ [scout] Search for recent LLM agent papers
    ✅ [deep_dive] Extract claims from top sources
    ✅ [verification] Cross-check conflicting claims
```

### Provide feedback

```bash
curl -X POST http://localhost:8000/research/feedback/1 \
  -H "Content-Type: application/json" \
  -d '{"is_correct": true}'
```

Increases/decreases source credibility scores for future research.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/research` | Create research task. Body: `{"query": "...", "max_sources": 50, "max_duration_minutes": 30}` |
| GET | `/research` | List all research tasks with status summary |
| GET | `/research/{task_id}` | Get task status details + step progress |
| GET | `/research/{task_id}/status` | SSE progress stream |
| GET | `/research/{task_id}/report` | Markdown report |
| GET | `/research/{task_id}/html` | Interactive HTML report |
| POST | `/research/feedback/{source_id}` | Source credibility feedback |
| GET | `/health` | System health + agent heartbeats |
| GET | `/cache/stats` | Source cache statistics |

---

## Configuration Reference

### Key environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARGUS_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `ARGUS_GROQ_API_KEY` | — | Groq free-tier API key |
| `ARGUS_GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model ID |
| `ARGUS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `ARGUS_OLLAMA_MODEL` | `llama3.2:3b` | Ollama model |
| `ARGUS_OPENROUTER_API_KEY` | — | OpenRouter API key |
| `ARGUS_OPENROUTER_MODEL` | `mistralai/mixtral-8x7b-instruct` | OpenRouter model |
| `ARGUS_OPENAI_COMPATIBLE_API_KEY` | — | Custom endpoint key |
| `ARGUS_OPENAI_COMPATIBLE_BASE_URL` | — | Custom endpoint URL |
| `ARGUS_SERPAPI_API_KEY` | — | SerpAPI search key |
| `ARGUS_FIRECRAWL_API_KEY` | — | Firecrawl API key |
| `ARGUS_FIRECRAWL_BASE_URL` | `https://api.firecrawl.dev` | Firecrawl API base |
| `ARGUS_BUDGET_PER_RESEARCH` | `0.50` | Maximum cost per query |
| `ARGUS_AGENT_CONCURRENCY` | `2` | Parallel agent count |
| `ARGUS_LLM_RETRY_MAX_ATTEMPTS` | `3` | LLM retry attempts |

Full list in `.env.example`.

---

## Architecture Overview

```
Query → Planner → Redis Streams → Agents → Write Queue → KG Writer → SQLite
                                                              ↓
                                                     SSE Streamer → Frontend
```

- **Planner** — classifies query, produces step DAG
- **Scout Agent** — web search, emits entities + sources
- **Deep-Dive Agent** — scrapes pages, extracts claims via LLM
- **Verification Agent** — detects conflicting claims
- **Synthesis Agent** — entity resolution, RELATED_TO edges
- **KG Writer** — single-process batch consumer for SQLite
- **Confidence Scoring** — auto-calculated on every claim
- **Report Generator** — Markdown or interactive HTML

### Cost-Aware LLM Routing

Every LLM call routes through a task-type-aware selector:

| Task Type | Primary | Fallback 1 | Fallback 2 |
|-----------|---------|------------|------------|
| Planning | Ollama | Groq | OpenRouter |
| Scout | Groq | Ollama | OpenRouter |
| Deep-dive | Ollama | Groq | OpenRouter |
| Verification | Groq | Ollama | OpenRouter |
| Synthesis | Ollama | Groq | OpenRouter |
| Conflict Resolution | Groq | OpenRouter | OpenAI-compatible |

---

## Troubleshooting

### "Connection refused" for Ollama

Ollama must be running: `ollama serve`. Verify with `curl http://localhost:11434/api/tags`.

### Groq API key fails validation

Check your key at https://console.groq.com/keys. The model `llama-3.1-8b-instant` must be available on your account.

### Firecrawl connection test fails

Make sure your API key is correct. The test sends `POST /v2/search` with a minimal payload. Verify your key at https://firecrawl.dev.

### Redis connection errors

Ensure Redis is running: `docker ps | findstr redis`. Start with `docker run -d --name argus-redis -p 6379:6379 redis:7-alpine`.

### No reports generated

Check the server logs for agent errors. Run `python -m argus --workers-only` to see worker logs more clearly. Verify Redis Streams are working.

### Re-run the setup wizard

```bash
python -m argus onboard
```

Already-configured providers show "Reconfigure?" — answer `n` to keep current settings, `y` to change them.

### Submit research from CLI

```bash
python -m argus research "your query" --max-sources 50 --time-limit 30
```

Options:
- `--max-sources`, `-s` — max sources to collect (1–500, default 50)
- `--time-limit`, `-t` — max research time in minutes (1–360, default 30)

### Available CLI commands

```bash
python -m argus onboard          # Provider setup wizard
python -m argus research ...     # Submit research query
python -m argus list             # List all research tasks
python -m argus status <task>    # Show task status + steps
```

### Ctrl+C during wizard

Pressing Ctrl+C exits cleanly with "Setup cancelled. No changes saved."
