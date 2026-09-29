# The local maintainer skill stays, and owns the cookbook that the server serves

`.claude/skills/stratz-analysis/` (local `client.py`, parquet on disk, DuckDB) stays for maintainer work in this repo: reproducible scripts in `analyses/`, joins across many datasets, and the skill's "learn" step. Its `references/` (schema, schema index, `cookbook.md`) are the canonical copies. The Docker build copies them into the server image, so a cookbook entry learned locally reaches every plugin user on the next deploy, with no plugin release. Plugin users can't write to the cookbook. Only the maintainer teaches it.

## Considered Options

- **Retire the local skill and use the plugin everywhere**: one path, but it loses local files, and the learning loop would have to move server-side.
- **A `suggest_cookbook_entry` tool**: lets users contribute, but needs review tooling. A follow-up if friends' sessions turn up good discoveries.

## Consequences

- In this repo, Claude Code may see both `stratz-analysis` (local) and `dota-analyst:stratz-analysis` (plugin). The local skill's description says it covers work in this repo.
