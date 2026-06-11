# dota-analyst — Design Document

Token-efficient, LLM-driven analysis of Dota 2 stats from the Stratz GraphQL API,
packaged as a Claude Agent Skill. This document is the handoff from the design
sessions; a fresh Claude session should read this before building anything.

## v1 scope

v1 is the **open-ended filesystem skill**: it should be able to take an arbitrary
Stratz analysis question, discover the right query shapes via schema-exploration
tooling, and answer it through the file workflow below. One knowledge file ships
in v1: `references/cookbook.md` — **mechanical, question-agnostic API knowledge**
(field semantics, traps, working query shapes) that the skill reads on demand
and appends to as it learns. The curated *policy* layer (metric definitions,
standing filters, playbooks) stays out — see "Deferred / future work" at the
end.

## Core idea

Bulk data must never pass through the LLM's context window. Claude writes query
scripts to disk, runs them, writes results to disk, and **peeks** at a few rows /
distinct values to understand shape. Token cost scales with what is *inspected*,
not what is *fetched*. Analysis proceeds table-by-table in a DAG manner; the final
deliverable is a reproducible script plus its output, not a pile of ad-hoc context.

## The loop (per analysis question)

1. **Triage**: result expected under ~100 rows? Call the API and answer inline.
   Otherwise, enter the file workflow below.
2. **Fetch** via the caching client (see below) — raw JSON lands in `data/raw/`.
3. **Flatten** nested JSON into tabular form → `data/flattened/` (parquet).
4. **Peek**: `head`, `count(*)`, `count(distinct)`, min/max dates — a few rows
   only, via DuckDB. Never dump whole tables into context.
5. **Iterate**: decide the next query from what the peek revealed; repeat 2–4.
6. **Deliver**: write one final analysis script that runs end-to-end from the
   cached/flattened data, plus the output (e.g., a top-10 table).
7. **Learn**: append durable, question-agnostic discoveries (field semantics,
   traps, working query shapes) to the skill's `cookbook.md`. Policy stays out.

## Skill layout (v1)

```text
.claude/skills/stratz-analysis/
├── SKILL.md                  # triage rule, the loop above, "never read schema whole"
├── scripts/                  # run these, never read them into context
│   └── client.py             # auth, retry, rate-limit, cache-by-query-hash
└── references/               # read on demand, never preloaded
    ├── stratz_schema.graphql # copied from exploring-anthropic-api repo (see below);
    │                         # ~10K lines / ~65K tokens — never read whole
    ├── schema-index.txt      # generated list of ~500 type names (~3K tokens) — the TOC
    └── cookbook.md           # self-accumulating: field semantics, traps, working
                              # query shapes; mechanical knowledge only, no policy
```

`client.py` is deliberately the **only** script. Schema lookup and data peeking
are left to Claude Code's own tools — grep/awk over the SDL, DuckDB one-liners
over parquet — which are more capable than any wrapper script we'd write.
SKILL.md carries the *instructions* (never read schema whole; peek, don't dump);
the skill's only hard dependency is a way to fetch from Stratz.

The schema SDL already exists at
`../exploring-anthropic-api/resources/stratz_schema.graphql` — copy it in rather
than re-dumping via introspection (no `dump_schema.py` in v1).
`schema-index.txt` is generated from the SDL by grepping the column-0
definition headers.

## Schema exploration (the schema is ~10K lines / ~65K tokens — never read whole)

- The root `DotaQuery` type (~100 lines) is the built-in table of contents.
- SDL is grep-friendly: definitions start at column 0 and end with a bare `}`,
  so a simple awk/grep block grab extracts any single type definition.
- Cold-start path: read root type → grep intent vocabulary (e.g. "win", "week",
  "hero") → extract only the matching type blocks. `schema-index.txt` (just the
  type names) covers the "what exists?" question for ~3K tokens.

## Caching client (`client.py`)

Cache key = sha256 of the canonicalized query+variables, 12 hex chars:

```python
def fetch(query: str, variables: dict | None = None, ttl_days: int = 7) -> dict:
    canonical = json.dumps({"q": " ".join(query.split()), "v": variables}, sort_keys=True)
    key = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    path = RAW_DIR / f"{key}.json"
    if path.exists() and age_days(path) < ttl_days:
        return json.loads(path.read_text())
    data = call_stratz(query, variables)
    path.write_text(json.dumps(data))
    (RAW_DIR / f"{key}.meta.json").write_text(json.dumps(
        {"query": query, "variables": variables, "fetched_at": now_iso()}))
    return data
```

Rules: never embed "now"/current timestamps inside the query text (kills cache
hits); `.meta.json` sidecars make the cache auditable; canonicalization =
whitespace-normalize the query, sort variable keys.

## Data layering (v1: two layers only)

```text
data/raw/        # JSON response cache keyed by query hash (+ .meta.json sidecars)
data/flattened/  # structural transformation only: nested JSON → tidy parquet tables
```

Parquet + ephemeral DuckDB (`duckdb.query("... from 'data/flattened/x.parquet'")`)
for all analyses. All of `data/` is gitignored.

## Secrets

- `STRATZ_TOKEN` (Stratz API) lives in `.env` / environment only. `.env` is
  gitignored. The committed skill must work from a fresh clone given only the
  env var. Never print tokens.

## Relationship to the existing MCP server

A Stratz MCP server (FastMCP, streamable HTTP) exists in the
`exploring-anthropic-api` repo (`mcp-servers/stratz-mcp-server/server.py`),
deployed on Render. It is **not used by this skill**: its tools return full
JSON payloads into LLM context, which is exactly the problem this design
avoids. This repo's `client.py` calls `https://api.stratz.com/graphql` directly
with `STRATZ_TOKEN`. The server stays relevant only for the deferred claude.ai
conversational variant.

## Build order

1. `scripts/client.py` (auth + retry + cache); copy
   `../exploring-anthropic-api/resources/stratz_schema.graphql` into
   `references/` and generate `schema-index.txt` from it.
2. `SKILL.md` with the loop, triage rule, and schema-exploration instructions.
3. Run one end-to-end analysis (e.g., weekly hero win rates by bracket) to
   validate the loop; harvest the first `cookbook.md` entries from it.

## Deferred / future work

Out of scope for v1, recorded here so the threads aren't lost:

- **Curated semantic layer**: PR-reviewed `metrics.md` (metric blocks: name,
  formula, grain, source path, standing filters, gotchas, sanity check),
  `filters.md` (standing filters), and `playbook.md` (suggested analyses /
  question patterns). Definitions agreed in the design sessions, preserved for
  when this lands: **win rate** = `winCount / matchCount`, grain hero-week from
  `heroStats.winWeek`, filter ALL_PICK_RANKED, suppress `matchCount < 200`,
  sanity: match-weighted mean ≈ 50%; **pick rate** =
  `heroMatchCount / (SUM(matchCount) / 10)` — denominator is *matches × 10 pick
  slots*, apply bracket/position filters to numerator and denominator
  consistently, sanity: pick rates sum to ~1000%; **contest rate** = pick +
  ban rate (to be written). Promote entries from the cookbook as they
  stabilize into policy.
- **`dump_schema.py`**: regenerate the SDL via introspection if the Stratz
  schema drifts from the copied snapshot.
- **`data/marts/` + warehouse promotion**: derived/aggregated tables for
  recurring themes; promote to a single `data/warehouse.duckdb` with policy
  views only when tables accumulate shared cross-session value (recurring
  themes, unambiguous grain).
- **Report template** (`assets/report_template.md`) for the deliverable step.
- **Distribution**: commit `.claude/skills/` for collaborators (this part may
  land naturally with v1); org-wide claude.ai conversational variant split into
  org **connector** = pipes + auth (the Render MCP server; needs OAuth — static
  bearer isn't supported by custom connectors — *open item*) and org **skill** =
  brains only (no scripts, no caching). Render free tier cold-starts in 50–90s,
  exceeding the 30s MCP connect timeout — wake via `/health` first or set
  `MCP_TIMEOUT=120000`.
