# The server copies `live.py` and `custom_layout.py` from `../dota` instead of sharing a package

The Stratz tooling (`../dota/src/dota/web/stratz/live.py`) and grid placement (`../dota/src/dota/core/custom_layout.py`) are copied here with provenance comments and are allowed to drift. The website's Gemini chat, their other user, is due to be retired once friends are on the plugin. A shared package would tie two repos together for code with one future user. Hosting the MCP server inside `../dota` would pull the pipeline's GCP and BigQuery dependencies into a public-facing server.

## Considered Options

- **Extract a shared package**: one source of truth, but versioning and releases across two hobby repos.
- **Host the MCP server in `../dota`**: reuses the package directly, but gives a public server the pipeline's dependencies.
