# dota-analyst

LLM-driven analysis of Dota 2 stats from the Stratz GraphQL API, built around a
Claude Agent Skill (`.claude/skills/stratz-analysis/`).

- **Read `DESIGN.md` before building or changing anything** — it carries the full
  architecture: the peek-iterate file workflow, caching client, data layering
  (`data/raw/` → `data/flattened/`), schema-exploration rules, and the
  self-accumulating cookbook (mechanical API knowledge only; the curated
  semantic layer is deferred).
- Never read `references/stratz_schema.graphql` in full (~65K tokens). Use the
  schema index and grep/awk to extract single type blocks.
- Bulk API data goes to disk, never into context. Peek at a few rows/distincts
  via DuckDB to understand shape.
- Secrets: `STRATZ_TOKEN` comes from the environment / `.env` (gitignored).
  Never commit or print tokens.
- `data/` is local cache + derived tables; it is gitignored and safe to delete.
