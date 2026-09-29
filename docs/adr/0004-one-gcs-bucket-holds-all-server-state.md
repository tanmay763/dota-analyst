# One GCS bucket holds all server state: a per-user dataset cache and used refresh-token markers

The bucket `dota-analyst-mcp` (asia-south1) has two prefixes with lifecycle deletes. `cache/` holds Stratz responses by query hash for 7 days, in front of a local `/tmp` copy. That keeps a dataset handle from `stratz_fetch` valid for a later `stratz_aggregate` after Cloud Run scales to zero (about 15 idle minutes, a normal pause while a friend reads) or when the call lands on another instance. `jti/` holds used refresh-token IDs for 90 days (ADR 0003). They're written with `ifGenerationMatch=0`, so marking a token used is an atomic create that fails if another request already did.

The cache is **namespaced per user** by a hash of their Stratz token. Stratz has viewer-scoped queries, and it isn't documented whether a token unlocks its owner's private data. With a shared cache, one friend's private results could be served to another who sent the same query. For a few users, cross-user cache hits would be rare anyway.

## Considered Options

- **`/tmp` only**: no service, but handles die after idle gaps, and the model has to refetch and spend Stratz calls.
- **Firestore**: good for the markers (transactions, TTL), but its 1 MiB document cap rules it out for Stratz responses, and it would mean a second service.
- **Fly Tigris or volumes**: only relevant if we leave GCP. GCS stays reachable from Fly through workload identity (the `../dota` ADR 0010 pattern).
- **Redis/Memorystore, Cloud SQL**: $30+ a month, or overkill.
