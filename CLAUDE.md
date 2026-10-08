# dota-analyst

Dota 2 analysis from the Stratz GraphQL API for Claude: a plugin (`plugin/`), the MCP
server it connects to (`src/dota_analyst_mcp/`), and the maintainer's local skill
(`.claude/skills/stratz-analysis/`), whose references the server serves.

- `CONTEXT.md` is the glossary: use its terms in code, issues and commits.
  Decisions live in `docs/adr/`; flag it when a change contradicts one.
- `docs/deployment.md` describes how the MCP server is hosted, credentialed, deployed
  and checked. Update it in the same change as anything deploy-side: `Dockerfile`,
  `.gcloudignore`, the Makefile's deploy targets, Cloud Run settings, secrets, the
  bucket, or IAM grants.
- Releases follow semver, with one version in `pyproject.toml` and the plugin manifest,
  and an entry in `CHANGELOG.md` (`docs/deployment.md`, "Releasing"). Note user-visible
  changes under `[Unreleased]` as you make them.
- Never read `references/stratz_schema.graphql` in full (~65K tokens). Use the
  schema index and grep/awk to extract single type blocks.
- Bulk API data goes to disk, never into context. Peek at a few rows/distincts
  via DuckDB to understand shape.
- Secrets: `STRATZ_TOKEN` comes from the environment / `.env` (gitignored).
  Never commit or print tokens.
- `data/` is local cache + derived tables; it is gitignored and safe to delete.

## Filing an analysis

`analyses/` holds repeatable analyses made with the maintainer skill, one folder each
(`analyses/<name>/`), in the same shape as ../aoe2-analyst:

- `<name>.py`, run from the repo root (`uv run analyses/<name>/<name>.py`). An analysis
  can have several scripts, such as a fetch and a report (see `analyses/ti2026/`).
- `<name>.context.json`: the user's original prompt **verbatim**, started with the first
  prompt, with later clarifications appended in order. Keep the analyst's interpreted
  question, scope and methodological choices separate from the user's words, and record
  the rerun command and each run (date, resolved period, code revision, report and output
  paths). A dynamic default such as "latest complete week" isn't the concrete week a run
  used, so record both. When a prompt is lost, write `null` and say why; never present
  reconstructed intent as a quote.
- `<slug>_YYYY-MM-DD.md`: one report per run, dated by the run and linked from `runs`.
  It's a snapshot: rerun and write a new report rather than editing an old one's numbers.
- `out/`: run output (JSON, HTML) under the report's dated name. It's gitignored because
  the rerun regenerates it, so the report must carry every number that matters.
