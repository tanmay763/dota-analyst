# Deployment specifics (GCP project, gcloud config) live in the gitignored local.mk; see
# local.mk.example. gcloud runs under the personal credentials, never the company ones.
-include local.mk

REGION  ?= asia-south1
SERVICE ?= dota-analyst-mcp
SA      ?= dota-analyst-mcp@$(PROJECT).iam.gserviceaccount.com
BUCKET  ?= dota-analyst-mcp
# Cloud Run's hash-form URL: unlike the <service>-<project number> form, it doesn't reveal
# the project (docs/adr/0005). OAuth sign-ins are bound to it, so changing it means reconnecting.
PUBLIC_URL ?= https://dota-analyst-mcp-rpuldjax7a-el.a.run.app
GCLOUD  = CLOUDSDK_CONFIG=$(GCLOUD_CONFIG) gcloud --project=$(PROJECT)
NEED_LOCAL = $(if $(and $(PROJECT),$(GCLOUD_CONFIG)),,$(error PROJECT or GCLOUD_CONFIG is unset: copy local.mk.example to local.mk and fill it in))

.DEFAULT_GOAL := help
.PHONY: help test lint serve gcloud-status deploy url release-check release

help:
	@echo "make test           pytest (no network, no credentials)"
	@echo "make lint           ruff check + ruff format --check"
	@echo "make serve          the MCP server on http://127.0.0.1:8000"
	@echo "make gcloud-status  the personal gcloud login and project (read-only)"
	@echo "make deploy         build and deploy the server to Cloud Run"
	@echo "make url            the deployed service URL"
	@echo "make release-check  every release check, without tagging or publishing"
	@echo "make release        tag vX.Y.Z and publish the GitHub release (docs/deployment.md)"

test:
	uv run pytest -q

lint:
	uv run ruff check src tests plugin scripts
	uv run ruff format --check src tests plugin scripts

serve:
	uv run dota-analyst-mcp

gcloud-status:
	$(NEED_LOCAL)
	$(GCLOUD) auth list
	$(GCLOUD) config list

deploy:
	$(NEED_LOCAL)
	$(GCLOUD) run deploy $(SERVICE) --source . --region=$(REGION) --quiet \
		--service-account=$(SA) --allow-unauthenticated \
		--min-instances=0 --max-instances=1 --cpu-boost --memory=1Gi \
		--labels=app=dota-analyst-mcp \
		--set-env-vars=DOTA_ANALYST_BUCKET=$(BUCKET),PUBLIC_URL=$(PUBLIC_URL) \
		--set-secrets=DOTA_ANALYST_SEAL_KEYS=dota-analyst-mcp-seal-keys:latest

url:
	$(NEED_LOCAL)
	@$(GCLOUD) run services describe $(SERVICE) --region=$(REGION) --format='value(status.url)'

release-check:
	uv run python scripts/release.py --dry-run

release:
	uv run python scripts/release.py
