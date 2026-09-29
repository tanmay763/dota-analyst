# The OAuth server registers clients by CIMD only and keeps tokens in sealed blobs, not a database

Clients identify themselves with a Client ID Metadata Document: the `client_id` is an HTTPS URL, which we fetch with SSRF guards (https only, no private IPs, 5 s timeout, 64 KB cap) and check its `redirect_uris` against. Dynamic Client Registration is deprecated in MCP 2026-07-28, and Claude uses CIMD whenever the authorization server metadata advertises `client_id_metadata_document_supported` and the `none` token auth method, so there's no client store. Authorization codes, access tokens (1 h) and refresh tokens (90 d) are Fernet-sealed blobs holding the Stratz token, the PKCE challenge or `resource`, and an expiry. Any instance can open them with the keys from Secret Manager (a `MultiFernet` list, so keys can rotate), and rotating every key revokes everything. Authorization responses carry `iss` (RFC 9207), and access tokens are checked against our canonical URL (RFC 8707).

The one piece of state is refresh-token reuse detection: OAuth 2.1 requires public clients' refresh tokens to rotate. Each refresh token's `jti` is marked used in GCS (ADR 0004), and a reused one is rejected.

## Considered Options

- **DCR as well**: kept out until a client we target needs it (maybe ChatGPT; a follow-up checks).
- **No refresh tokens, 30-day access tokens**: no state, but friends re-paste their token monthly.
- **Stateless refresh tokens without reuse detection**: rotation in name only, falling short of OAuth 2.1 for public clients.
- **Tokens in a database**: more infrastructure than a handful of users needs.
