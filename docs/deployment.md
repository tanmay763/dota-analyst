# Deployment

One deployment: the MCP server the plugin connects to (ADR 0001, 0005). The plugin itself
isn't deployed. People install it from this repo, which is its own marketplace (ADR 0010),
and it points at the server through `plugin/.mcp.json`.

| | MCP server |
|---|---|
| **What** | `dota_analyst_mcp.app`: Stratz tools, sign-in with a user's own Stratz token, the hero grid app and download links |
| **Host** | Cloud Run service `dota-analyst-mcp`, `asia-south1`, in the GCP project named in `local.mk` |
| **URL** | `https://dota-analyst-mcp-rpuldjax7a-el.a.run.app` (MCP endpoint `/mcp`), Cloud Run's hash-form URL, which doesn't reveal the project |
| **Scaling** | min 0, max 1 instance, 1 GiB, request-based billing, `--cpu-boost`. An instance starts in about 3.6 s |
| **Build** | `Dockerfile`: `uv sync --frozen --no-dev` on `python:3.13-slim`, built by Cloud Build from `gcloud run deploy --source .` |
| **Deploys** | By hand: `make deploy`. Nothing deploys automatically |
| **GCP identity** | Service account `dota-analyst-mcp` |
| **Secrets** | `DOTA_ANALYST_SEAL_KEYS`, from Secret Manager. There is no Stratz token: every user brings their own (ADR 0002) |
| **Cost** | Inside Cloud Run's free tier at a few users; the bucket holds megabytes. A budget alert (₹850/month, about $10) watches for floods (below) |

## Google Cloud resources

All in one GCP project, named in `local.mk` and shared with `../dota`, but separate from
its accounts and buckets. The service account has only what the server uses (the `../dota` ADR 0011
pattern):

| Resource | What it holds | Access |
|---|---|---|
| Service account `dota-analyst-mcp@…` | The Cloud Run service's identity | No project-level roles |
| Bucket `gs://dota-analyst-mcp` (`asia-south1`, uniform access, public access prevented) | All server state (ADR 0004): `cache/<user>/` Stratz responses, `constants/` the hero list, `jti/` used codes and refresh tokens | Storage Object User for the service account |
| Secret `dota-analyst-mcp-seal-keys` | Comma-separated Fernet keys that seal sign-ins and tokens (ADR 0003) | Secret Accessor for the service account |
| Artifact Registry `cloud-run-source-deploy` (`asia-south1`) | Images built by `make deploy` | Created by gcloud |

The bucket's lifecycle rules delete `cache/` and `constants/` objects after 7 days and
`jti/` after 90. Those ages match the cache TTL and the refresh-token lifetime; don't
shorten `jti/` below the refresh-token lifetime, or a used token could be replayed.

## gcloud and `local.mk`

The GCP project and the gcloud configuration directory are kept out of the public repo, in
a gitignored `local.mk` (copy `local.mk.example`). The Makefile reads them, and its gcloud
targets stop with a hint when `local.mk` is missing.

Every gcloud command uses the personal credentials in `$(GCLOUD_CONFIG)`, never the
company ones; the Makefile sets `CLOUDSDK_CONFIG` for its own targets. Before any gcloud
work, run `make gcloud-status`: it must show your personal account and the project. If the
login is stale, run `CLOUDSDK_CONFIG=<GCLOUD_CONFIG> gcloud auth login`. The commands
below write `<project>` and `<GCLOUD_CONFIG>` for the values in `local.mk`.

## Deploying

```sh
make test lint     # nothing deploys that fails these
make deploy        # build with Cloud Build, roll out a new revision
```

`make deploy` sets the environment on every deploy:

| Variable | Value | Why |
|---|---|---|
| `PUBLIC_URL` | the hash-form URL above | The OAuth issuer and the resource `/mcp` must match the URL exactly; sign-ins are bound to it, so changing it means everyone reconnects |
| `DOTA_ANALYST_BUCKET` | `dota-analyst-mcp` | Where state lives; without it the server uses a local directory |
| `DOTA_ANALYST_SEAL_KEYS` | `dota-analyst-mcp-seal-keys:latest` | Mounted from Secret Manager |

It also labels the service `app=dota-analyst-mcp`, which the budget filters on.

`.gcloudignore` limits the upload to the build's inputs (`src/`, the lockfile, the
Dockerfile and the maintainer skill's `references/`), so `.env`, `local.mk` and `data/`
never leave the machine.

**Cookbook changes ship with a deploy.** The image copies
`.claude/skills/stratz-analysis/references/` (ADR 0009), so after the maintainer teaches
the cookbook something, `make deploy` delivers it to every plugin user.

**Plugin changes ship with a push.** Skills, README and `.mcp.json` reach users from the
repo's default branch.

## Releasing

Versions follow semver and are shared by the plugin and the server:

1. Raise `version` in `pyproject.toml` and `plugin/.claude-plugin/plugin.json` together,
   and run `uv lock`. `tests/test_release.py` fails if they differ.
2. Move the `[Unreleased]` notes in `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`, and add
   the version's link at the bottom.
3. Merge to `main` through a pull request, then `make deploy`. The server reports the
   version in its MCP server info.
4. On the merged `main`, run `make release-check`, then `make release`. It checks that
   `main` is clean and matches `origin/main`, that the versions agree, that the changelog
   has the section, and that the tag is new, and it runs the tests and lint. Then it tags
   `vX.Y.Z`, pushes the tag, and publishes the GitHub release with that changelog section
   as the notes (`scripts/release.py`).

## Budget alert

A ₹850/month budget (about $10; the billing account is in INR, and a budget must use its
currency) on the project's billing account emails the billing admins at 50%, 90% and 100%. It counts **gross** cost, with credits excluded (otherwise the project's credits
would hide a flood), and only resources labelled `app=dota-analyst-mcp`. Normal use is
about $0, so any alert means unusual traffic. A sustained flood is capped by
`max-instances=1` at roughly one instance-month (about $70). To look at it:

```sh
CLOUDSDK_CONFIG=<GCLOUD_CONFIG> gcloud billing budgets list \
  --billing-account=<billing account> --billing-project=<project>
```

Pass `--billing-project`: without it, gcloud bills the Budgets API call to the
configuration's default quota project, which may be another project with the API off.

## Rotating the sealing keys

The first key seals; every key opens. To rotate without signing anyone out, add a new
version with the new key first and the old one after it, deploy, and remove the old key
after 90 days. To sign everyone out at once (e.g. a leaked key), add a version with only
a new key and deploy. Users reconnect and paste their Stratz token again.

```sh
CLOUDSDK_CONFIG=<GCLOUD_CONFIG> gcloud secrets versions add dota-analyst-mcp-seal-keys \
  --project=<project> --data-file=- <<< "$(uv run python -c \
  'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode(), end="")'),<old key>"
make deploy
```

## Checking a deployment

- `curl <URL>/health` answers `ok`.
- `curl <URL>/.well-known/oauth-authorization-server` shows the service URL as `issuer`,
  with `client_id_metadata_document_supported` and
  `authorization_response_iss_parameter_supported` both `true`.
- A `POST <URL>/mcp` without a token answers `401` with a `resource_metadata` pointer.
- End to end: `uv run scripts/e2e_check.py <URL>` signs in as Claude Code (real CIMD,
  loopback redirect) with the maintainer's `STRATZ_TOKEN`. It calls every tool against
  live Stratz, downloads the grid, probes the refusals, and exits 1 on any failure.
  `.claude/skills/verify/SKILL.md` has the whole verification recipe. For the plugin's own
  behaviour, connect it in Claude, ask a question, then ask for a hero grid.

## Troubleshooting

- **Stratz errors name Cloudflare.** Cloudflare is challenging Cloud Run's egress IPs
  (it already blocks GitHub Actions). Retrying won't help. The fallback is Fly.io `bom` or
  `sin` (ADR 0005). GCS stays reachable from Fly through workload identity.
- **"Couldn't reach the MCP server" when connecting.** Check `/health`, then the metadata
  URLs above. A `421` means `PUBLIC_URL` doesn't match the host being called.
- **Every user is signed out.** The sealing keys changed without keeping the old key, or
  the secret wasn't mounted (the logs warn that `DOTA_ANALYST_SEAL_KEYS` is unset).
- **"This sign-in link expired."** The connect page lasts 15 minutes; start connecting again.
- **Logs:** `CLOUDSDK_CONFIG=<GCLOUD_CONFIG> gcloud logging read
  'resource.labels.service_name="dota-analyst-mcp"' --project=<project> --freshness=1h`. The server never logs Stratz tokens. Sealed blobs appear in URLs but
  can't be opened without the keys.
