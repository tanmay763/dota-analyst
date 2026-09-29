# The dota-analyst MCP server (docs/adr/0005): Cloud Run, asia-south1.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# The schema and cookbook the tools serve are the maintainer skill's (docs/adr/0009).
COPY .claude/skills/stratz-analysis/references ./references
ENV DOTA_ANALYST_REFERENCES=/app/references PATH="/app/.venv/bin:$PATH"

CMD ["dota-analyst-mcp"]
