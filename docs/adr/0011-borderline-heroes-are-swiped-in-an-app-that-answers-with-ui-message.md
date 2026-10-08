# Borderline heroes are swiped in an MCP App that answers with `ui/message`

Before the first build of a hero grid, Claude can put up to five borderline heroes (close calls in or out of a layout) to the user. `review_borderline_heroes` takes each hero's name, the category it would go in and one line of evidence, resolves the names like `build_hero_grid` does, and returns them as cards for the MCP App `ui://hero-swipe`. The user swipes right to keep a hero and left to leave it out, with buttons, arrow keys and undo for the same actions. When the stack is done, a **Send to Claude** button sends the verdicts through `ui/message` as a user message, which starts Claude's turn to build the grid.

This is the first app that writes back to Claude. ADR 0006 keeps the grid preview read-only, with edits in chat. The swipe app follows the same idea: its result is an ordinary chat message, so Claude and the user see the same text, and the grid is still built only by Claude calling `build_hero_grid`.

The send is a button, not the last swipe, so the user can undo before anything reaches Claude. When the host refuses the message or doesn't support it, the app shows the sentence for the user to paste. Where apps don't render (Claude Code), the tool's text tells Claude to ask in chat.

Verdicts live only in the app's page. When the host re-renders the app, for example on reopening the conversation, the stack starts again. That's acceptable because the message that was sent stays in the conversation.

## Considered Options

- **`ui/update-model-context`**: hosts may hold the update until the user's next message, so Claude wouldn't act on the verdicts until the user typed something (the lag noted in #5).
- **The app calls `build_hero_grid` itself through `tools/call`**: the app would need the whole draft grid, and the result would land in the swipe app rather than in a grid preview Claude knows about.
- **Swipe cards inside the grid preview**: mixes a read-only preview with an input step and makes `grid.html` carry two jobs.
