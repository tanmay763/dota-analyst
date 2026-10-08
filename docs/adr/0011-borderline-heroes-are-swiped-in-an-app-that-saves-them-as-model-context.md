# Borderline heroes are swiped in an MCP App that saves the verdicts as model context

Before the first build of a hero grid, Claude can put up to five borderline heroes (close calls in or out of a layout) to the user. `review_borderline_heroes` takes each hero's name, the category it would go in and one line of evidence, resolves the names like `build_hero_grid` does, and returns them as cards for the MCP App `ui://hero-swipe`. The user swipes right to keep a hero and left to leave it out, with buttons, arrow keys and undo for the same actions.

When the last card is decided, the app saves the verdicts with `ui/update-model-context`, as text and as `{kept, dropped}`, and says "Preferences saved. Type go to continue." The host gives that context to Claude with the user's next message, so "go" starts Claude's turn to build the grid. An undo followed by a new decision saves again, and the newer update replaces the older one. When the host doesn't support the update or refuses it, the app shows the sentence for the user to tell Claude. Where apps don't render (Claude Code), the tool's text tells Claude to ask in chat.

The app never writes into the chat box. Whatever reaches Claude as the user's message is typed by the user, and the grid is still built only by Claude calling `build_hero_grid`, as in ADR 0006.

Verdicts live only in the app's page and the host's saved context. When the host re-renders the app, for example on reopening the conversation, the stack starts again.

## Considered Options

- **`ui/message`** (what shipped in 0.2.0): the app posts the verdicts as the user's message. On claude.ai the host didn't send it. It put the text into the chat box under a prompt-injection warning ("Use caution before running this prompt…") and waited for the user to press Enter, while the app said "Sent to Claude." Text an app writes into the user's chat box is the wrong channel even when the host asks first.
- **The app calls `build_hero_grid` itself through `tools/call`**: the app would need the whole draft grid, and the result would land in the swipe app rather than in a grid preview Claude knows about.
- **Swipe cards inside the grid preview**: mixes a read-only preview with an input step and makes `grid.html` carry two jobs.
