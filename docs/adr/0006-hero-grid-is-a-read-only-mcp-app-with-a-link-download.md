# The hero grid shows as a read-only MCP App preview and downloads through a stateless link

`build_hero_grid` takes layouts as rows of named categories of hero names, resolves the names, places them with `custom_layout.place_grid` (copied from `../dota`), and returns the placed grid in two forms. The MCP App `ui://hero-grid` is a port of the website's `grid.js` preview, with portraits from `cdn.steamstatic.com` declared in its CSP. It renders the grid in Claude web, desktop, mobile and ChatGPT. The text result carries a `/grid/<blob>.json` link: the blob is the compressed layout itself, so the endpoint needs no auth or storage and serves `hero_grid_config.json` as an attachment. The app's Download button opens the same link via `openLink()`, because app iframes can't download files, and Claude asks the user to confirm external links for custom connectors. Claude Code doesn't render apps and just shows the text with the link.

Edits happen in chat ("move Pudge to the offlane box"), and each one re-calls the tool and re-renders the preview. That's the flow that worked on the website. The model never re-types the config JSON.

Dota reads a single grid file, so the grid skill warns that ours replaces the user's current grid. It offers `merge_grid.py`, run in code execution on the user's uploaded file: layouts with the same name are replaced and the rest appended. The user's file never reaches our server.

## Considered Options

- **Download link only**: works everywhere, but there's no preview. That's the part of the website that turned out well.
- **An editable app** (drag heroes, sync back with `updateModelContext`): Claude and the app can briefly disagree, because model-context updates may arrive a turn late. It's a follow-up.
- **Config JSON in the chat**: the model re-types kilobytes of JSON and mistypes it.
