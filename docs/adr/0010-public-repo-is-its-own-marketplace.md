# The public repo is its own plugin marketplace, and the plugin lives in `plugin/`

`.claude-plugin/marketplace.json` at the repo root lists one plugin, `plugin/`. Friends add the repo URL under Customize > Plugins > Add marketplace, and a push reaches them without anyone sending a zip. A plugin ships its whole folder to everyone who installs it, so the plugin folder holds only the manifest, `.mcp.json`, skills, README and LICENSE (MIT). The server, tests, analyses and Dockerfile stay outside it. The manifest `name` is `dota-analyst`. Users install and address skills by that name, so it never changes (`displayName` can). Before the repo goes public, its history is scanned for secrets.

## Considered Options

- **The plugin at the repo root**: every installer would receive the server source and analyses.
- **A private repo and zip uploads**: every update means resending a file, and a directory listing needs a public source anyway.
