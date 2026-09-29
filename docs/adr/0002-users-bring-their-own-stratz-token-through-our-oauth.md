# Each user brings their own Stratz token, entered through our own OAuth sign-in

Connecting the plugin runs a standard OAuth flow against an authorization server co-hosted with the MCP server. Its sign-in page asks for the user's Stratz API token (free from stratz.com/api), checks it with a cheap query, and issues OAuth tokens that carry it. Every Stratz call is then made with the caller's own token, so each user spends their own rate limit (20/s, 250/min, 2,000/h, 10,000/day on a free token), and the server never needs a Stratz token of its own. Stratz offers no OAuth for third parties, so a paste-your-token page is the only way to get a user's token through a standard connector sign-in.

## Considered Options

- **One shared server token, no sign-in**: simplest, but anyone with the URL spends our limit, and it would share the weekly pipeline's token unless a new one were minted. Unfit for a public listing.
- **A shared token behind Steam sign-in, with per-user quotas**: still one Stratz limit for everyone, and it needs an OAuth shim anyway.
- **Static request headers**: Claude's `static_headers` connector auth is in beta and set by an organization Owner, not by each user.
- **The token as a tool argument**: it would land in conversation transcripts.
