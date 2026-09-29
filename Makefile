# gcloud runs under the personal credentials (../dota's CLAUDE.md), never the company ones.
PROJECT ?= <gcp-project>
REGION  ?= asia-south1
SERVICE ?= dota-analyst-mcp
SA      ?= dota-analyst-mcp@$(PROJECT).iam.gserviceaccount.com
BUCKET  ?= dota-analyst-mcp
PUBLIC_URL ?= https://$(SERVICE)-<project-number>.$(REGION).run.app
GCLOUD  = CLOUDSDK_CONFIG=$(HOME)/.config/gcloud-personal gcloud --project=$(PROJECT)

.DEFAULT_GOAL := help
.PHONY: help test lint serve gcloud-status deploy url

help:
	@echo "make test           pytest (no network, no credentials)"
	@echo "make lint           ruff check + ruff format --check"
	@echo "make serve          the MCP server on http://127.0.0.1:8000"
	@echo "make gcloud-status  the personal gcloud login and project (read-only)"
	@echo "make deploy         build and deploy the server to Cloud Run"
	@echo "make url            the deployed service URL"

test:
	uv run pytest -q

lint:
	uv run ruff check src tests plugin
	uv run ruff format --check src tests plugin

serve:
	uv run dota-analyst-mcp

gcloud-status:
	$(GCLOUD) auth list
	$(GCLOUD) config list

# PUBLIC_URL is the service's own URL (project number <project-number>); `make url` confirms it.
deploy:
	$(GCLOUD) run deploy $(SERVICE) --source . --region=$(REGION) --quiet \
		--service-account=$(SA) --allow-unauthenticated \
		--min-instances=0 --max-instances=3 --cpu-boost --memory=1Gi \
		--set-env-vars=DOTA_ANALYST_BUCKET=$(BUCKET),PUBLIC_URL=$(PUBLIC_URL) \
		--set-secrets=DOTA_ANALYST_SEAL_KEYS=dota-analyst-mcp-seal-keys:latest

url:
	@$(GCLOUD) run services describe $(SERVICE) --region=$(REGION) --format='value(status.url)'
