# Agent Protocols

## Redis Stream Message Formats

### Task Queue (`tasks` stream)

Produced by: Planner (via ResearchManager)
Consumed by: Agent Workers (via consumer groups)

```json
{
  "idempotency_key": "0195c8e0-...",
  "task_id": "task-uuid",
  "step_id": 1,
  "type": "discover",
  "agent": "scout",
  "goal": "Find top 10 AI code review tools",
  "depends_on": "[]"
}
```

Consumer group: `argus-workers`
Message IDs: Redis auto-generated (timestamp-sequence)

### Fact Stream (`facts` stream)

Produced by: Agent Workers
Consumed by: KG Writer, Synthesis Agent

```json
{
  "idempotency_key": "0195c8e1-...",
  "data": "{\"facts\": [...], \"task_id\": \"...\", \"step_id\": 1}",
  "agent": "scout"
}
```

Raw stream entry fields:
- `idempotency_key` (bytes): UUID v7
- `data` (bytes): JSON-encoded fact batch
- `agent` (bytes): Agent type that emitted

#### Fact Batch Schema (inside `data`):

```json
{
  "idempotency_key": "uuid-v7",
  "task_id": "task-uuid",
  "step_id": 1,
  "agent": "scout",
  "facts": [
    {"type": "entity", "name": "OpenAI", "task_id": "..."},
    {"type": "claim", "statement": "...", "entity_name": "OpenAI", "source_urls": ["..."], "task_id": "..."},
    {"type": "source", "url": "https://...", "title": "...", "task_id": "..."}
  ]
}
```

### Progress Stream (`progress:{task_id}`)

Produced by: Agent Workers (via AgentRunner)
Consumed by: SSE Streamer → browser client

```json
{
  "type": "step_start",
  "data": "{\"step_id\": 1, \"agent\": \"scout\"}"
}
```

Event types:
- `step_start` — Agent begins processing a step
- `step_complete` — Agent finishes, includes facts_count
- `research_done` — All steps finished
- `research_failed` — Fatal error, includes error message
- `budget_exceeded` — Cost cap reached

### Dead-Letter Queue (`dlq` stream)

Produced by: Any consumer pushing failed messages
Consumed by: DLQConsumer

```json
{
  "original_message": "{\"task_id\": \"...\", \"step_id\": 1, ...}",
  "reason": "Rate limit exceeded after 3 retries",
  "failed_at": "1712345678.123",
  "requeue_count": "0",
  "target_stream": "tasks"
}
```

## Idempotency Protocol

### UUID v7 Generation

```python
from uuid import uuid7
key = str(uuid7())  # e.g., "0195c8e0-1234-7abc-def0-123456789abc"
```

### Dedup Check

Every message sent to any Redis stream includes an `idempotency_key`.
The KG Writer and all consumers check this key via `IdempotencyChecker`:

1. Hash the key with SHA256
2. Check `processed_keys` SQLite table
3. If exists and not expired → skip message
4. If not exists → process and mark

### TTL

Default: 24 hours (configurable via `ARGUS_LLM_CACHE_TTL`)

## Stream Consumption Patterns

### Task Queue (Consumer Groups)

```python
r.xreadgroup("argus-workers", "scout-worker-1", {"tasks": ">"}, count=1, block=2000)
```

- Auto-ack on success via `xack`
- No ack on failure → message remains pending → other worker picks up after CLAIM_TIMEOUT (30s)
- Max retries before DLQ: configured via MAX_REQUEUES (default 3)

### Fact Stream (Independent Consumers)

```python
r.xread({"facts": last_id}, count=10, block=2000)
```

- KG Writer and Synthesis Agent both read independently
- Each tracks their own `last_id` cursor
- No ack needed (at-least-once via idempotency key)

### Progress Stream (Short-lived)

```python
r.xread({"progress:{task_id}": "$"}, count=10, block=30000)
```

- `$` starts from latest (new events only)
- Maxlen trimmed to 10,000 entries
- SSE streamer reads and yields to HTTP client

## Error Handling

### Retry Policy

```python
@tenacity.retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=10),
)
```

Applied to: All LLM provider calls, archive operations

### Circuit Breaker States

| State | Behavior | Recovery |
|-------|----------|----------|
| CLOSED | Normal operation | — |
| OPEN | Fast-fail all requests | Auto-transition after 30s |
| HALF_OPEN | Allow one test request | Success → CLOSED, Fail → OPEN |

### DLQ Re-queue Backoff

| Attempt | Delay | Action |
|---------|-------|--------|
| 1st failure | 0 | Push to DLQ |
| 1st re-queue | 5s | Back to original stream |
| 2nd re-queue | 30s | Back to original stream |
| 3rd re-queue | 120s | Back to original stream |
| 4th failure | archive | Deleted from DLQ |

## Agent Types and Task Types

| Agent Type | Task Type | Purpose |
|------------|-----------|---------|
| `scout` | `discover` | Web search for candidate entities |
| `deep_dive` | `extract` | Scrape URLs and extract structured facts |
| `verification` | `verify` | Cross-check claims for conflicts |
| `synthesis` | `synthesize` | Entity resolution, relation extraction (continuous) |

## Heartbeat Protocol

- Every agent writes to Redis key `heartbeat:{agent_id}` with TTL 30s
- Refresh interval: 10s (TTL/3)
- Health endpoint reads all heartbeats, reports stale agents as warning
- Agent IDs format: `{agent_type}-worker-{unix_timestamp}`

## SSE Event Format

```
data: {"type": "step_start", "task_id": "abc", "step_id": 1, "agent": "scout", "message": "Starting discovery"}

data: {"type": "step_complete", "task_id": "abc", "step_id": 1, "agent": "scout", "message": "Found 10 entities", "data": {"facts_count": 10}}

data: {"type": "research_done", "task_id": "abc", "message": "Research complete"}
```
