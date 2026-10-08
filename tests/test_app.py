"""The MCP server end to end: a signed-in SDK client calls every tool over HTTP.

The client runs the 2026-07-28 protocol against the ASGI app in-process, with the access
token from a real (stubbed-Stratz) sign-in, so auth, tool schemas and results are all real.
"""

import contextlib

import httpx2
import pytest
from conftest import PUBLIC_URL
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from dota_analyst_mcp.app import create_app

WIN_WEEK = "query ($w: Int) { heroStats { winWeek(take: $w) { week heroId matchCount winCount } } }"
WIN_WEEK_DATA = {
    "heroStats": {
        "winWeek": [
            {"week": 100, "heroId": 1, "matchCount": 50, "winCount": 30},
            {"week": 100, "heroId": 2, "matchCount": 40, "winCount": 10},
        ]
    }
}
HEROES_DATA = {
    "constants": {
        "heroes": [
            {"id": 1, "displayName": "Anti-Mage", "shortName": "antimage"},
            {"id": 2, "displayName": "Axe", "shortName": "axe"},
            {"id": 86, "displayName": "Rubick", "shortName": "rubick"},
        ]
    }
}
TOOLS = [
    "stratz_cookbook",
    "stratz_schema_search",
    "stratz_schema_type",
    "stratz_fetch",
    "stratz_aggregate",
    "build_hero_grid",
    "review_borderline_heroes",
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def connect(settings, tokens):
    app = create_app(settings)

    @contextlib.asynccontextmanager
    async def open_client(token: str | None = None):
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=PUBLIC_URL,
            headers={"Authorization": f"Bearer {token or tokens['access_token']}"},
        )
        # The ASGI transport doesn't run lifespans; the SDK's session manager needs one.
        transport = streamable_http_client(f"{PUBLIC_URL}/mcp", http_client=http)
        async with app.router.lifespan_context(app), Client(transport) as client:
            yield client

    return open_client


@pytest.mark.anyio
async def test_tools_are_listed_in_a_fixed_order_with_instructions(connect):
    async with connect() as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOLS)
        assert [t.name for t in listed.tools] == [
            t.name for t in (await client.list_tools()).tools
        ]
        assert "Bulk data never belongs in the conversation" in (
            client.instructions or ""
        )
        fetch = next(t for t in listed.tools if t.name == "stratz_fetch")
        assert fetch.annotations.read_only_hint is True


@pytest.mark.anyio
async def test_fetch_then_aggregate_with_the_users_token(connect, stratz):
    calls, queue = stratz
    queue.append((200, {"data": WIN_WEEK_DATA}))
    async with connect() as client:
        fetched = await client.call_tool(
            "stratz_fetch", {"query": WIN_WEEK, "variables": {"w": 1}}
        )
        assert not fetched.is_error
        dataset = fetched.structured_content["dataset"]
        assert fetched.structured_content["tables"][0]["rows"] == 2
        summed = await client.call_tool(
            "stratz_aggregate",
            {
                "datasets": {"w": dataset},
                "sql": "SELECT sum(matchCount) AS n FROM w_heroStats_winWeek",
            },
        )
        assert summed.structured_content["rows"] == [[90]]
    assert calls[-1]["headers"]["Authorization"] == "Bearer friend-stratz-token"


@pytest.mark.anyio
async def test_a_bad_query_comes_back_to_the_model_readably(connect, stratz):
    _, queue = stratz
    queue.append((200, {"errors": [{"message": 'Cannot query field "winWeak"'}]}))
    async with connect() as client:
        result = await client.call_tool("stratz_fetch", {"query": WIN_WEEK})
        assert result.is_error and "winWeak" in result.content[0].text


@pytest.mark.anyio
async def test_schema_and_cookbook_tools(connect):
    async with connect() as client:
        sections = await client.call_tool("stratz_cookbook", {})
        assert "heroStats.winWeek" in sections.structured_content["sections"]
        found = await client.call_tool("stratz_schema_search", {"term": "herostat"})
        assert "HeroStatsQuery" in found.structured_content["types"]
        block = await client.call_tool("stratz_schema_type", {"name": "HeroStatsQuery"})
        assert block.structured_content["definition"].startswith("type HeroStatsQuery")
        missing = await client.call_tool(
            "stratz_schema_type", {"name": "HeroStatQuery"}
        )
        assert missing.is_error and "HeroStatsQuery" in missing.content[0].text


@pytest.mark.anyio
async def test_build_hero_grid_returns_the_grid_for_the_app_and_a_link_for_the_model(
    connect, stratz
):
    _, queue = stratz
    queue.append((200, {"data": HEROES_DATA}))
    layouts = [
        {
            "name": "Carry tiers",
            "rows": [
                [
                    {"name": "S", "heroes": ["Anti-Mage"]},
                    {"name": "A", "heroes": ["axe", "Rubick"]},
                ]
            ],
        }
    ]
    async with connect() as client:
        result = await client.call_tool("build_hero_grid", {"layouts": layouts})
    assert not result.is_error
    data = result.structured_content
    assert [c["config_name"] for c in data["grid"]["configs"]] == ["Carry tiers"]
    assert data["heroes"]["1"] == {"name": "Anti-Mage", "short_name": "antimage"}
    assert data["download_url"].startswith(f"{PUBLIC_URL}/grid/")
    text = result.content[0].text
    assert data["download_url"] in text and "replaces the grid" in text


@pytest.mark.anyio
async def test_unknown_heroes_build_nothing(connect, stratz):
    _, queue = stratz
    queue.append((200, {"data": HEROES_DATA}))
    layouts = [{"name": "X", "rows": [[{"name": "S", "heroes": ["Pudgee"]}]]}]
    async with connect() as client:
        result = await client.call_tool("build_hero_grid", {"layouts": layouts})
    assert result.is_error and "Nothing was built" in result.content[0].text


@pytest.mark.anyio
async def test_the_app_resource_declares_the_portrait_cdn(connect):
    async with connect() as client:
        tools = (await client.list_tools()).tools
        build = next(t for t in tools if t.name == "build_hero_grid")
        assert build.meta["ui"]["resourceUri"] == "ui://hero-grid"
        assert (
            build.meta["ui/resourceUri"] == "ui://hero-grid"
        )  # the flat key, for older hosts
        resource = await client.read_resource("ui://hero-grid")
    (content,) = resource.contents
    assert content.mime_type == "text/html;profile=mcp-app"
    assert content.meta["ui"]["csp"]["resourceDomains"] == [
        "https://cdn.steamstatic.com"
    ]
    assert "ui/initialize" in content.text and "ui/open-link" in content.text


@pytest.mark.anyio
async def test_borderline_heroes_return_cards_for_the_app_and_a_prompt_for_the_model(
    connect, stratz
):
    _, queue = stratz
    queue.append((200, {"data": HEROES_DATA}))
    candidates = [
        {"hero": "rubick", "category": "Pos 4 · B", "note": "52% win rate, 1% picks"},
        {"hero": "Axe", "category": "Offlane · A", "note": "thin sample"},
    ]
    async with connect() as client:
        result = await client.call_tool(
            "review_borderline_heroes", {"candidates": candidates}
        )
    assert not result.is_error
    (rubick, axe) = result.structured_content["candidates"]
    assert rubick == {
        "hero_id": 86,
        "name": "Rubick",
        "short_name": "rubick",
        "category": "Pos 4 · B",
        "note": "52% win rate, 1% picks",
    }
    assert axe["name"] == "Axe"
    text = result.content[0].text
    assert "Rubick (Pos 4 · B)" in text and "type 'go'" in text


@pytest.mark.anyio
async def test_unknown_borderline_heroes_show_nothing(connect, stratz):
    _, queue = stratz
    queue.append((200, {"data": HEROES_DATA}))
    async with connect() as client:
        result = await client.call_tool(
            "review_borderline_heroes",
            {"candidates": [{"hero": "Pudgee", "category": "S", "note": ""}]},
        )
    assert result.is_error and "Nothing was shown" in result.content[0].text


@pytest.mark.anyio
async def test_the_swipe_app_resource_declares_the_portrait_cdn(connect):
    async with connect() as client:
        tools = (await client.list_tools()).tools
        review = next(t for t in tools if t.name == "review_borderline_heroes")
        assert review.meta["ui"]["resourceUri"] == "ui://hero-swipe"
        assert review.meta["ui/resourceUri"] == "ui://hero-swipe"
        resource = await client.read_resource("ui://hero-swipe")
    (content,) = resource.contents
    assert content.mime_type == "text/html;profile=mcp-app"
    assert content.meta["ui"]["csp"]["resourceDomains"] == [
        "https://cdn.steamstatic.com"
    ]
    assert "ui/initialize" in content.text
    assert "ui/update-model-context" in content.text
