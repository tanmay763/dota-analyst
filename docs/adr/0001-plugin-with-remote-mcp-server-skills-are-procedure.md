# The analyst ships as a Claude plugin: a remote MCP server does the Stratz work, and the skills are procedure only

Friends should get this repo's analysis quality without cloning it or running Claude Code, and the `../dota` website's Gemini chat is the thing being replaced. The plugin contains two skills (`stratz-analysis`, `hero-grid-builder`) and a `.mcp.json` pointing at our hosted MCP server. It installs on claude.ai web, desktop, mobile, Cowork and Claude Code. In chat, a skill can't reach an outside service, and plugin files can't hold secrets, so every Stratz call, schema lookup, cookbook read and grid placement happens server-side. The skills only teach the workflow: triage, cookbook first, fetch, peek at the shape, aggregate, answer, then *offer* a grid rather than building one.

The server keeps the file workflow's rule that bulk data never enters the model's context. `stratz_fetch` returns a dataset handle and a shape summary, and `stratz_aggregate` runs SQL server-side and returns at most 100 rows. This is the design `../dota` proved in `live.py` (its ADR 0009).

## Considered Options

- **Skills only, with scripts calling Stratz from the code-execution sandbox**: blocked in chat (no route to outside services, nowhere to keep a token), and useless on mobile.
- **A local (stdio) MCP server or `.mcpb` bundle**: chat ignores local servers, so it would only work in Claude Code and Cowork on a desktop.
- **Keep improving the website with Gemini**: cheaper per token, but answer quality was the problem.

## Consequences

- The server's tool descriptions carry the workflow's discipline, so clients without our skills (e.g. ChatGPT) still behave.
- Built on MCP spec 2026-07-28 and the Python SDK `mcp` v2 (`MCPServer`). The protocol has no sessions, so state crosses calls only as server-minted handles passed as tool arguments.
