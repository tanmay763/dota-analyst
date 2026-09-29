# The server runs on Cloud Run in asia-south1, scaled to zero, on its run.app URL

It runs in the existing GCP project to use its credits, with Cloud Run's request-based billing and min-instances 0. At the usage of a couple of friends that's inside the permanent free tier, so it costs roughly nothing, and a warm instance isn't worth paying for. It uses a least-privilege service account `dota-analyst-mcp`, with Storage Object User on its bucket and Secret Accessor on its key secret only (the `../dota` ADR 0011 pattern). To meet Claude's 10 s limit on OAuth endpoints from a cold start, duckdb and pandas load lazily, the image stays slim, and `--cpu-boost` is on.

Stratz sits behind Cloudflare, which blocks GitHub Actions. On 2026-09-28, a throwaway Cloud Run job in asia-south1 sent one request from each of three egress IPs. All three reached Stratz (`403 "A bearer token is required"`, cf-ray `…-BOM`), not a challenge. Egress IPs come from a shared, changing pool, so that lowers the risk but doesn't remove it. If the server ever meets a challenge, its error names Cloudflare (`describe_failure`), and the fallback is Fly.io `bom` or `sin` (the website already reaches Stratz from `sin`). No `fly.toml` exists until then.

Cloud Run domain mapping isn't available in asia-south1, so the URL is `*.run.app`. It stays stable while the service exists. Changing it means a plugin release, and every user reconnects.

## Considered Options

- **Fly.io**: known to reach Stratz, and faster resume from suspend, but no free allowance for new orgs, and the state would live outside GCP.
- **A custom domain**: needs a global load balancer (about $18/month), Firebase Hosting (a hard 60 s rewrite timeout), or moving to asia-southeast1. Revisit before a directory listing.
- **min-instances 1**: no cold starts, but not justified for a hobby project.
