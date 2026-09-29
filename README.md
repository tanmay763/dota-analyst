# dota-analyst

Dota 2 analysis from [Stratz](https://stratz.com) for Claude, packaged as a Claude plugin.

- `plugin/`: the plugin people install (skills, connector reference). See its
  [README](plugin/README.md).
- `src/dota_analyst_mcp/`: the MCP server the plugin connects to: Stratz tools, sign-in
  with a user's own Stratz token, and the hero grid app. Runs on Cloud Run.
- `.claude/skills/stratz-analysis/`: the maintainer's local skill, which owns the Stratz
  schema and cookbook the server serves.
- `docs/adr/`: the decisions behind all of this. `CONTEXT.md`: the glossary.

## Install the plugin

In Claude, go to **Customize > Plugins > Add marketplace** and enter
`https://github.com/tanmay763/dota-analyst`. In Claude Code:
`/plugin marketplace add tanmay763/dota-analyst`.

## Develop

```sh
make test     # pytest, no network
make serve    # the MCP server on http://127.0.0.1:8000
```
