# Knowledge Graph Schema

## SQLite Database

File: `~/.argus/knowledge.db` (configurable via `ARGUS_SQLITE_PATH`)

## Tables

### `entities`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `name` | TEXT NOT NULL | Entity name |
| `type` | TEXT | Entity type (company, paper, person, etc.) |
| `description` | TEXT | Optional description |
| `confidence` | REAL | 0.0–1.0, aggregated from claims |
| `attributes` | TEXT (JSON) | Flexible key-value attributes |
| `task_id` | TEXT NOT NULL | Originating research task |
| `created_at` | TEXT | ISO 8601 timestamp |
| `updated_at` | TEXT | ISO 8601 timestamp |

### `claims`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `statement` | TEXT NOT NULL | Claim text |
| `confidence` | REAL | 0.0–1.0, calculated from formula |
| `entity_id` | INTEGER FK → entities | Subject entity |
| `attribute` | TEXT | Claim attribute name (e.g., "pricing", "employees") |
| `source_urls` | TEXT (JSON array) | Supporting source URLs |
| `task_id` | TEXT NOT NULL | Originating research task |
| `created_at` | TEXT | ISO 8601 timestamp |

### `sources`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `url` | TEXT NOT NULL | Source URL |
| `title` | TEXT | Page title |
| `content_hash` | TEXT | SHA256 of scraped content |
| `credibility_score` | REAL | 0.0–1.0, domain-based + learning |
| `task_id` | TEXT NOT NULL | Originating research task |
| `fetched_at` | TEXT | ISO 8601 timestamp |

### `edges`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `source_id` | INTEGER NOT NULL | Source node ID |
| `target_id` | INTEGER NOT NULL | Target node ID |
| `relation_type` | TEXT | RELATES_TO, SUPPORTS, CONFLICTS_WITH, HAS_CLAIM, CITED_BY |
| `weight` | REAL | Edge weight (0.0–1.0) |
| `task_id` | TEXT NOT NULL | Originating research task |
| `created_at` | TEXT | ISO 8601 timestamp |

### `processed_keys`

| Column | Type | Description |
|--------|------|-------------|
| `key_hash` | TEXT PK | SHA256 of idempotency key |
| `created_at` | REAL | Unix timestamp |
| `ttl_seconds` | REAL | TTL for this key (default 86400) |

### Source Cache (in-memory table)

| Column | Type | Description |
|--------|------|-------------|
| `url_hash` | TEXT PK | SHA256 of URL |
| `url` | TEXT | Full URL |
| `markdown` | TEXT | Scraped markdown content |
| `content_type` | TEXT | MIME type |
| `fetched_at` | REAL | Unix timestamp |
| `keep` | INTEGER | 1 = user-marked for indefinite storage |

## FTS5 Virtual Table

```sql
CREATE VIRTUAL TABLE claims_fts USING fts5(
    statement, entity_name,
    content='claims',
    content_rowid='id'
);
```

Synchronized via triggers on INSERT to claims table.

## vec0 (HNSW) Virtual Tables

```sql
CREATE VIRTUAL TABLE vec_entities USING vec0(embedding float[384]);
CREATE VIRTUAL TABLE vec_claims USING vec0(embedding float[384]);
```

- 384 dimensions (all-MiniLM-L6-v2 compatible)
- HNSW index for ANN search
- EF construction: 200, M: 16 (configurable)

## Recursive CTE: Provenance Chain

```sql
WITH RECURSIVE provenance AS (
    SELECT id, statement, entity_id, source_urls, task_id, created_at, 0 AS depth
    FROM claims WHERE id = ?
    UNION ALL
    SELECT e.id, e.name, e.id, '{}', e.task_id, e.created_at, p.depth + 1
    FROM provenance p
    JOIN entities e ON e.id = p.entity_id
    WHERE p.depth < 5
)
SELECT * FROM provenance ORDER BY depth;
```

## Indexes

| Table | Index | Columns |
|-------|-------|---------|
| entities | idx_entities_name | name |
| entities | idx_entities_task_id | task_id |
| claims | idx_claims_entity_id | entity_id |
| claims | idx_claims_task_id | task_id |
| sources | idx_sources_url | url |
| sources | idx_sources_task_id | task_id |
| edges | idx_edges_source | source_id |
| edges | idx_edges_target | target_id |
| edges | idx_edges_task_id | task_id |

## WAL Mode

```sql
PRAGMA journal_mode = WAL;
PRAGMA cache_size = -64000;  -- 64MB
```
