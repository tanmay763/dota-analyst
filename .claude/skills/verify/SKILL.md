---
name: verify
description: >-
  How to verify a change in the dota-analyst repo at its real surface: the MCP
  server over HTTP (local or deployed), the plugin's skills and preview in
  Claude, the analyses, and the release script. Use with /verify, or when
  asked to check that a change works.
---

# Verifying dota-analyst

Run from the repo root. uv's `UV_ENV_FILE=.env` setting makes `uv run` fail
anywhere else. `STRATZ_TOKEN` comes from `.env`; never print it.

## The MCP server (`src/dota_analyst_mcp/`, cookbook, Dockerfile)

The surface is HTTP, the way a Claude client uses it. `scripts/e2e_check.py`
drives all of it and prints PASS/FAIL per check, exiting 1 on any failure:

- **the refusals it probes:** an unauthenticated 401, a wrong Stratz token and a reused
  code;
- **the sign-in:** OAuth metadata, then a sign-in through Claude Code's real CIMD
  (Client ID Metadata Document) with a loopback redirect;
- **the tools:** all of them, against live Stratz, including a refused mutation;
- **the grid:** building it and downloading `hero_grid_config.json`.

**Local:** start the server in the background, wait for `/health`, run the check,
then stop the server:

```sh
DOTA_ANALYST_STATE_DIR=$(mktemp -d) uv run dota-analyst-mcp   # background; port 8000
uv run scripts/e2e_check.py                                   # defaults to http://127.0.0.1:8000
pkill -f dota-analyst-mcp
```

**Deployed** (after `make deploy`; needs `local.mk`):

```sh
uv run scripts/e2e_check.py https://dota-analyst-mcp-rpuldjax7a-el.a.run.app
```

- For a cookbook change, add `--cookbook "<section title>"` to print the section as
  the server serves it. The server only serves a new cookbook after `make deploy`,
  because the image copies `.claude/skills/stratz-analysis/references/` at build time.
- For a change to a specific tool, drive that tool too, with the same sign-in.
  `scripts/e2e_check.py` exposes `sign_in(base, token)`, which returns an access token.
- Server logs:
  `CLOUDSDK_CONFIG=<GCLOUD_CONFIG> gcloud logging read 'resource.labels.service_name="dota-analyst-mcp"' --project=<project> --freshness=1h`,
  with the values from `local.mk`.

**Gotchas:**
- The CIMD sign-in fetches `https://claude.ai/oauth/claude-code-client-metadata`, so
  it needs network access.
- A request to any host other than the one in `PUBLIC_URL` gets **421**. The old
  project-number URL is meant to fail.
- The script calls live Stratz, and the numbers depend on the data. Stratz's hero stats
  can lag by days.

## The plugin (`plugin/`: skills, README, `.mcp.json`)

The surface is Claude itself, and only the maintainer's Claude account can install
the plugin there. Ask the user to update the marketplace, or reinstall it, and run
the prompts that exercise the change. Two examples:

- an analysis question: it shouldn't build a grid unasked;
- "make that a tier list grid": the preview should render, and the download link
  should work.

`claude plugin validate ./plugin` checks the files, not the behaviour. `claude plugin
eval` (#14) is the automated way to check skill behaviour.

The hero grid preview (`src/dota_analyst_mcp/ui/grid.html`) renders only in Claude
web, desktop or mobile, not in Claude Code. The script checks that the tool returns
the grid and the link, but the pixels need the user, or Claude Desktop with developer
mode's inspector.

## Analyses (`analyses/<name>/`)

Run the analysis script from the repo root, as its `.context.json` `rerun` says.
Scripts that read cached `data/raw/` files are deterministic. Scripts that fetch live
data aren't, so compare the output's shape, not its numbers.

## Releasing (`scripts/release.py`, Makefile)

`make release-check` is the dry run. Probe it with a dirty tree, a branch other
than `main`, or an existing tag: each must be refused with a message naming the
problem. Never run `make release` just to verify: it tags and publishes.
