---
name: stratz-analysis
description: >-
  Analyze Dota 2 statistics via the Stratz GraphQL API. Use when the user asks
  about Dota 2 data of any kind — hero win/pick rates, meta trends, player or
  match performance, leagues, items, lanes, brackets — or wants an analysis,
  table, or report built from Stratz data.
---

# Stratz Dota 2 Analysis

Core discipline: **bulk data never enters your context**. Fetch to disk, peek
at a few rows to learn shape, analyze with scripts. Token cost must scale with
what you *inspect*, not what you *fetch*.

Requires `STRATZ_TOKEN` in the environment or repo `.env`. Run everything with
`uv run` from the repo root (deps: httpx, python-dotenv, duckdb).

## The loop (per analysis question)

1. **Triage**: will the result be under ~100 rows? Fetch and answer inline.
   Otherwise follow steps 2–6.
2. **Fetch** via the caching client — raw JSON lands in `data/raw/`:

   ```sh
   uv run .claude/skills/stratz-analysis/scripts/client.py \
     --query 'query ($n: Int) { ... }' --variables '{"n": 5}'
   ```

   It prints the cache file path, never the payload. From Python:
   `from client import fetch` (add the scripts dir to `sys.path`), then
   `fetch(query, variables)` → the response's `data` dict. Identical
   query+variables hit the disk cache (default TTL 7 days).
3. **Flatten**: write the nested JSON as one or more tidy parquet tables in
   `data/flattened/`, e.g.

   ```sh
   duckdb -c "COPY (SELECT unnest(heroStats.winWeek, recursive := true)
     FROM read_json('data/raw/<hash>.json')) TO 'data/flattened/<name>.parquet'"
   ```

   (In Python scripts, `import duckdb` and `duckdb.sql(...)` — the package is a
   project dep.)
4. **Peek** to learn shape — a few rows only, never whole tables:
   `LIMIT 5`, `count(*)`, `count(DISTINCT col)`, `min/max` of keys and dates,
   e.g. `duckdb -c "SELECT * FROM 'data/flattened/<name>.parquet' LIMIT 5"`.
5. **Iterate**: let what the peek revealed drive the next query; repeat 2–4.
6. **Deliver**: consolidate into one reproducible script in `analyses/` that
   runs end-to-end from the raw cache, plus its printed output (e.g. a top-10
   table). Intermediate exploration snippets don't need to survive.
7. **Learn**: append durable, question-agnostic discoveries — field semantics,
   traps, working query shapes — to `references/cookbook.md` as entries under
   the API path they describe. Skip anything question-specific or policy-like
   (metric definitions, standing filters).

## Schema exploration

**Check `references/cookbook.md` first** — known field semantics, traps, and
working query shapes live there and may answer the question without touching
the schema.

`references/stratz_schema.graphql` is ~10K lines / ~65K tokens. **Never read
it whole.** It is grep-friendly: every definition starts at column 0 and ends
with a bare `}`.

- What exists? → `references/schema-index.txt` (500 type names, ~one screen
  per grep).
- What can be queried? → the root type is the table of contents:
  `awk '/^type DotaQuery /,/^}/' references/stratz_schema.graphql` (~100 lines).
- Drill into a type the same way: `awk '/^type HeroStatsQuery /,/^}/' ...`
- Searching by intent ("win", "week", "ward") → grep the index first, then
  extract only the matching blocks.

(Reference paths above are relative to this skill's directory.)

## Rules

- Never embed "now"/current timestamps in query text — it kills cache hits.
  Pass changing values as GraphQL variables.
- GraphQL errors raise `StratzError` and are not cached: fix the query, don't
  blind-retry. Check field names against the schema first.
- Filters like bracket/position/gameMode must be applied consistently across
  numerator and denominator of any rate metric.
- `data/` is a disposable, gitignored cache — safe to delete, never commit.
- Never print or commit `STRATZ_TOKEN`.
