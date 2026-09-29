"""The dota-analyst MCP server (ADR 0001): tools, the hero grid app, sign-in and downloads.

Configuration comes from the environment:

- `PUBLIC_URL`: the server's public origin, e.g. https://dota-analyst-mcp-xyz.a.run.app
  (default http://127.0.0.1:8000). The MCP endpoint is `<PUBLIC_URL>/mcp`.
- `DOTA_ANALYST_SEAL_KEYS`: comma-separated Fernet keys; the first seals, all open (ADR 0003).
  Without it a throwaway key is generated, so sign-ins last only as long as the process.
- `DOTA_ANALYST_BUCKET`: the GCS bucket holding server state (ADR 0004); without it, state
  lives in `DOTA_ANALYST_STATE_DIR` (default `data/server`).
- `PORT`: where uvicorn listens (default 8000).
"""

import html
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio.to_thread
from cryptography.fernet import Fernet
from mcp.server.apps import Apps, ResourceCsp
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.routes import cors_middleware
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import Route

from dota_analyst_mcp import __version__, grid, stratz
from dota_analyst_mcp.auth import (
    Sealer,
    StratzAccessToken,
    StratzOAuthProvider,
    fetch_client_document,
)
from dota_analyst_mcp.store import GcsStore, LocalStore, Store

logger = logging.getLogger(__name__)

UI = Path(__file__).parent / "ui"
HEROES_TTL = 24 * 3600
TOKEN_CHECK_QUERY = "{ constants { gameVersions { id } } }"

INSTRUCTIONS = """\
Dota 2 statistics from Stratz, and in-game hero grids built from them.

Bulk data never belongs in the conversation. Check stratz_cookbook first, look types up with
stratz_schema_search / stratz_schema_type, then stratz_fetch once: it returns a dataset handle
and each table's shape, never the rows. Answer with stratz_aggregate (SQL, at most 100 rows).
State the period (default: the latest complete week), ranks and metric behind every number.
Build a hero grid only when the user asks for one, after the analysis is done.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@dataclass
class Settings:
    public_url: str
    seal_keys: list[str]
    store: Store
    fetch_document: Callable[[str], tuple[dict, int] | None] = field(
        default=fetch_client_document
    )
    clock: Callable[[], float] = field(default=time.time)

    @classmethod
    def from_env(cls) -> "Settings":
        keys = [k for k in os.getenv("DOTA_ANALYST_SEAL_KEYS", "").split(",") if k]
        if not keys:
            logger.warning(
                "DOTA_ANALYST_SEAL_KEYS unset: sign-ins last only as long as this process"
            )
            keys = [Fernet.generate_key().decode()]
        bucket = os.getenv("DOTA_ANALYST_BUCKET")
        store = (
            GcsStore(bucket)
            if bucket
            else LocalStore(Path(os.getenv("DOTA_ANALYST_STATE_DIR", "data/server")))
        )
        public_url = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
        return cls(public_url=public_url, seal_keys=keys, store=store)


class CategorySpec(BaseModel):
    name: str = Field(
        description="The category's label, e.g. 'S' or 'Lane dominators'."
    )
    heroes: list[str] = Field(
        description="Hero names, best first, e.g. ['Anti-Mage', 'Faceless Void']."
    )


class LayoutSpec(BaseModel):
    name: str = Field(
        description="The layout's name, as picked in the Dota client. Unique within the grid."
    )
    rows: list[list[CategorySpec]] = Field(
        description="Rows of categories, top to bottom; at most 3 categories per row."
    )


def _stratz_token() -> str:
    token = get_access_token()
    if not isinstance(token, StratzAccessToken):
        raise ToolError("Not signed in: reconnect the dota-analyst connector.")
    return token.stratz_token


async def _run(fn, *args):
    """Blocking Stratz and DuckDB work runs off the event loop; expected failures reach the model."""
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args))
    except (stratz.StratzToolError, grid.GridError) as exc:
        raise ToolError(str(exc)) from exc


def create_server(settings: Settings) -> tuple[MCPServer, StratzOAuthProvider, "Tools"]:
    provider = StratzOAuthProvider(
        issuer=settings.public_url,
        resource=f"{settings.public_url}/mcp",
        sealer=Sealer(settings.seal_keys),
        store=settings.store,
        fetch_document=settings.fetch_document,
        clock=settings.clock,
    )
    tools = Tools(settings, stratz.LiveStratz(settings.store, clock=settings.clock))
    apps = Apps()

    @apps.tool(
        resource_uri="ui://hero-grid",
        # The deprecated flat key too, as the ext-apps SDK's registerAppTool() sets it:
        # hosts that read only this key would otherwise never show the preview.
        meta={"ui/resourceUri": "ui://hero-grid"},
        name="build_hero_grid",
        title="Build a hero grid",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        description=(
            "Turn layouts of hero names into an in-game Dota hero grid, with a preview and a "
            "download link. Call it only when the user asks for a grid, after the analysis. "
            "Each layout is rows of named categories (at most 3 per row, heroes best first); "
            "the server places and sizes them and returns warnings to act on. To change a "
            "layout, call again with the whole grid."
        ),
    )
    async def build_hero_grid(layouts: list[LayoutSpec]) -> CallToolResult:
        return await tools.build_hero_grid([layout.model_dump() for layout in layouts])

    apps.add_html_resource(
        "ui://hero-grid",
        (UI / "grid.html").read_text(),
        title="Hero grid preview",
        csp=ResourceCsp(resource_domains=["https://cdn.steamstatic.com"]),
    )

    mcp = MCPServer(
        "dota-analyst",
        title="Dota Analyst",
        version=__version__,
        instructions=INSTRUCTIONS,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=settings.public_url,
            resource_server_url=f"{settings.public_url}/mcp",
            validate_token_resource=True,
        ),
        extensions=[apps],
    )

    @mcp.tool(
        title="Read the Stratz cookbook", annotations=READ_ONLY, structured_output=True
    )
    def stratz_cookbook(section: str | None = None) -> dict[str, Any]:
        """Known Stratz field meanings, traps and working query shapes. Call with no section
        for the section titles, then read the ones that fit before writing any query."""
        try:
            result = stratz.cookbook(section)
        except stratz.StratzToolError as exc:
            raise ToolError(str(exc)) from exc
        return {"sections": result} if section is None else {"section": result}

    @mcp.tool(
        title="Search the Stratz schema", annotations=READ_ONLY, structured_output=True
    )
    def stratz_schema_search(term: str) -> dict[str, Any]:
        """Schema type names and root query fields containing a term, e.g. 'win' or 'lane'."""
        return stratz.schema_search(term)

    @mcp.tool(
        title="Read a Stratz schema type", annotations=READ_ONLY, structured_output=True
    )
    def stratz_schema_type(name: str, docs: bool = False) -> dict[str, Any]:
        """One type's definition from the Stratz GraphQL schema (fields and arguments; set
        docs for Stratz's descriptions too). Never ask for the whole schema."""
        try:
            return {"definition": stratz.schema_type(name, docs)}
        except stratz.StratzToolError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(title="Fetch from Stratz", annotations=READ_ONLY, structured_output=True)
    async def stratz_fetch(query: str, variables: dict | None = None) -> dict[str, Any]:
        """Run one read-only GraphQL query against Stratz. Returns a dataset handle and each
        table's name, row count, columns and 5 sample rows, never the full data. Pass
        changing values as variables so identical questions hit the cache."""
        return await _run(tools.stratz.fetch, _stratz_token(), query, variables)

    @mcp.tool(
        title="Aggregate Stratz data", annotations=READ_ONLY, structured_output=True
    )
    async def stratz_aggregate(datasets: dict[str, str], sql: str) -> dict[str, Any]:
        """SQL (DuckDB) over fetched datasets. `datasets` maps a short alias to a dataset
        handle, e.g. {"w": "3fa2c1d09b7e"}; each dataset's tables are named
        `<alias>_<table>`, e.g. w_heroStats_winWeek. Returns at most 100 rows."""
        return await _run(tools.stratz.aggregate, _stratz_token(), datasets, sql)

    return mcp, provider, tools


class Tools:
    """Tool bodies that need the store or Stratz, kept testable without a server."""

    def __init__(self, settings: Settings, live: stratz.LiveStratz):
        self.settings = settings
        self.stratz = live
        self._heroes: tuple[float, grid.Heroes] | None = None

    def heroes(self, token: str) -> grid.Heroes:
        now = self.settings.clock()
        if self._heroes and self._heroes[0] > now:
            return self._heroes[1]
        import json

        hit = self.settings.store.read("constants/heroes.json")
        if hit is not None and now - hit[1] < HEROES_TTL:
            data = json.loads(hit[0])
        else:
            data = self.stratz.post(token, grid.HEROES_QUERY)
            self.settings.store.write(
                "constants/heroes.json", json.dumps(data).encode()
            )
        heroes = grid.Heroes.from_constants(data)
        self._heroes = (now + HEROES_TTL, heroes)
        return heroes

    def download_url(self, layouts: list[dict]) -> str:
        return f"{self.settings.public_url}/grid/{grid.encode(layouts)}.json"

    def _build(self, token: str, layouts: list[dict]) -> CallToolResult:
        heroes = self.heroes(token)
        resolved = grid.resolve_layouts(layouts, heroes)
        placed, warnings = grid.place(resolved)
        url = self.download_url(resolved)
        lines = []
        for config in placed["configs"]:
            bottom = max(
                (c["y_position"] + c["height"] for c in config["categories"]), default=0
            )
            count = sum(len(c["hero_ids"]) for c in config["categories"])
            lines.append(
                f"- {config['config_name']}: {len(config['categories'])} categories, "
                f"{count} heroes, {round(bottom)} units tall"
            )
        text = "\n".join(
            ["Hero grid built:", *lines]
            + ([f"Warnings (act on these): {'; '.join(warnings)}"] if warnings else [])
            + [
                f"Download: {url}",
                (
                    "Install: save it as Steam/userdata/<your Steam ID>/570/remote/cfg/"
                    "hero_grid_config.json. It replaces the grid already there."
                ),
            ]
        )
        used = {
            i
            for config in placed["configs"]
            for c in config["categories"]
            for i in c["hero_ids"]
        }
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={
                "grid": placed,
                "heroes": {str(i): heroes.card(i) for i in sorted(used)},
                "warnings": warnings,
                "download_url": url,
            },
        )

    async def build_hero_grid(self, layouts: list[dict]) -> CallToolResult:
        return await _run(self._build, _stratz_token(), layouts)


# --- HTTP routes ------------------------------------------------------------------------

CONNECT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect Dota Analyst</title>
<style>
:root {{ color-scheme: dark; --bg:#15100c; --surface:#221913; --line:#3a2d23; --text:#e7dfd3; --muted:#9aa2b4; --accent:#c8412d; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:30rem; margin:10vh auto; padding:0 16px; }}
h1 {{ letter-spacing:.12em; text-transform:uppercase; font-size:1rem; }}
p, li {{ color:var(--muted); }}
strong {{ color:var(--text); }}
input {{ width:100%; box-sizing:border-box; padding:10px; background:var(--surface); color:var(--text); border:1px solid var(--line); border-radius:4px; font:inherit; }}
button {{ margin-top:12px; padding:10px 18px; border:0; border-radius:4px; background:var(--accent); color:#fff; font:inherit; cursor:pointer; }}
.error {{ color:#e0b070; }}
a {{ color:var(--text); }}
</style></head><body><main>
<h1>Connect Dota Analyst</h1>
<p><strong>{client}</strong> wants to query Stratz for you. After you connect, you'll be sent back to <strong>{host}</strong>. Continue only if you started this from there.</p>
<p>Paste your Stratz API token. Get one at <a href="https://stratz.com/api" target="_blank" rel="noopener">stratz.com/api</a>: sign in with Steam and copy the token. Your queries run on your token's rate limit, and the server never stores it.</p>
{error}
<form method="post" action="/connect">
<input type="hidden" name="request" value="{request}">
<input name="token" type="password" autocomplete="off" placeholder="Stratz API token" required autofocus>
<button type="submit">Connect</button>
</form>
</main></body></html>
"""


def _connect_page(
    request_blob: str, claims: dict, error: str = "", status: int = 200
) -> HTMLResponse:
    host = urlparse(claims["redirect_uri"]).hostname or claims["redirect_uri"]
    client = urlparse(claims["client_id"]).hostname or claims["client_id"]
    return HTMLResponse(
        CONNECT_PAGE.format(
            client=html.escape(client),
            host=html.escape(host),
            request=html.escape(request_blob),
            error=f'<p class="error">{html.escape(error)}</p>' if error else "",
        ),
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
    )


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or Settings.from_env()
    mcp, provider, tools = create_server(settings)

    async def connect(request: Request) -> Response:
        if request.method == "GET":
            blob = request.query_params.get("request", "")
            claims = provider.open_request(blob)
            if claims is None:
                return PlainTextResponse(
                    "This sign-in link expired. Start connecting again.", 400
                )
            return _connect_page(blob, claims)
        form = await request.form()
        blob = str(form.get("request", ""))
        claims = provider.open_request(blob)
        if claims is None:
            return PlainTextResponse(
                "This sign-in link expired. Start connecting again.", 400
            )
        token = str(form.get("token", "")).strip().strip('"')
        if not token:
            return _connect_page(blob, claims, "Paste your Stratz API token.", 400)
        try:
            await anyio.to_thread.run_sync(
                lambda: tools.stratz.post(token, TOKEN_CHECK_QUERY)
            )
        except stratz.StratzToolError as exc:
            return _connect_page(
                blob, claims, f"Stratz didn't accept that token: {exc}", 400
            )
        return RedirectResponse(provider.complete(claims, token), status_code=302)

    async def download(request: Request) -> Response:
        try:
            placed, _ = grid.place(grid.decode(request.path_params["blob"]))
        except grid.GridError as exc:
            return PlainTextResponse(str(exc), 400)
        return Response(
            grid.to_json(placed),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="hero_grid_config.json"'
            },
        )

    async def health(request: Request) -> Response:
        return PlainTextResponse("ok")

    async def as_metadata(request: Request) -> Response:
        return JSONResponse(
            provider.metadata().model_dump(mode="json", exclude_none=True),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    host = urlparse(settings.public_url).netloc
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[
            settings.public_url,
            "http://127.0.0.1:*",
            "http://localhost:*",
        ],
    )
    app = mcp.streamable_http_app(
        stateless_http=True, transport_security=security, host="0.0.0.0"
    )
    # Ours first: the SDK's authorization server metadata advertises neither CIMD nor `iss`.
    app.router.routes[0:0] = [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(as_metadata, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        ),
        Route("/connect", connect, methods=["GET", "POST"]),
        Route("/grid/{blob}.json", download, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
    ]
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
