# Changelog

All notable changes to the dota-analyst plugin and its MCP server. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0.0, a minor version may break
things: tool names and arguments, skill behaviour, or the connector URL.

## [Unreleased]

### Added

- `make release-check` and `make release`: check that `main`, the versions and the
  changelog are ready, then tag, push and publish the GitHub release
  (`scripts/release.py`).
- A $10/month budget alert on the server's resources, counting cost before credits.

### Changed

- The server runs at most one instance, which caps the cost of a flood.
- The GCP project and gcloud configuration moved from the Makefile and docs into a
  gitignored `local.mk` (`local.mk.example` shows the shape).

## [0.1.0] - 2026-09-29

The first release: Dota 2 analysis from Stratz as a Claude plugin, with in-game hero
grids.

### Added

- **The `dota-analyst` plugin** (`plugin/`), installable from this repo as a marketplace:
  - the `stratz-analysis` skill: cookbook first, schema lookup, fetch once, peek at the
    shape, aggregate in SQL, and state the period, ranks and metric. It offers a hero grid
    at the end rather than building one unasked;
  - the `hero-grid-builder` skill: agrees on the layouts (and a tier list's ranking logic)
    before building, hands over the download and install path, and warns that the file
    replaces the current grid;
  - `merge_grid.py`, which merges a new grid into the user's current
    `hero_grid_config.json` by layout name.
- **The MCP server** (`src/dota_analyst_mcp/`), on MCP spec 2026-07-28 with the Python SDK
  v2; 2025-11-25 clients are still served:
  - tools `stratz_cookbook`, `stratz_schema_search`, `stratz_schema_type`, `stratz_fetch`
    (a dataset handle and each table's shape, never the rows), `stratz_aggregate` (DuckDB
    SQL over one or more datasets, at most 100 rows) and `build_hero_grid`;
  - a hero grid preview as an MCP App (`ui://hero-grid`), with a stateless download link
    that also appears in the text reply;
  - sign-in with each user's own Stratz token through an OAuth 2.1 server: Client ID
    Metadata Documents, sealed codes and tokens, `iss` in responses, rotating refresh
    tokens that work once;
  - a per-user dataset cache and used-token markers in one GCS bucket.
- **Deployment** to Cloud Run in asia-south1 (`make deploy`, [docs/deployment.md](docs/deployment.md)).
- **Decisions** in [docs/adr/](docs/adr/) (0001 to 0010) and a glossary in
  [CONTEXT.md](CONTEXT.md).
- **Analyses** filed as `analyses/<name>/` with a context file and dated reports: BLAST
  Slam VII, the weekly win rates by rank, and The International 2026 (report, scouting and
  draft boards).
- The cookbook's `heroStats.itemFullPurchase` section, from ../dota.

### Changed

- The local `stratz-analysis` skill is now the maintainer's skill. Its schema and cookbook
  are what the server serves, so a cookbook entry reaches plugin users with the next deploy.

### Removed

- `DESIGN.md`, replaced by the ADRs; its deferred work is in issues #1 to #3.
- The placeholder `main.py`.

### Fixed

These were caught while testing before the release:

- `stratz_aggregate` failed on time-zone-aware timestamps (`to_timestamp`) because `pytz`
  was missing.
- The hero grid preview didn't render in Claude: its handshake sent `clientInfo` where
  hosts require `appInfo`, and the tool lacked the flat `ui/resourceUri` key that some
  hosts read.

[Unreleased]: https://github.com/tanmay763/dota-analyst/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tanmay763/dota-analyst/releases/tag/v0.1.0
