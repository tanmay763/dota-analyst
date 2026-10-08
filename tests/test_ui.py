"""The hero grid apps: the preview draws cards with the same geometry the server places
them with, and both apps load only portraits and speak the handshake hosts validate."""

import re
from pathlib import Path

import pytest

from dota_analyst_mcp import layout

UI = Path(layout.__file__).parent / "ui"
HTML = (UI / "grid.html").read_text()
SWIPE = (UI / "swipe.html").read_text()
APPS = pytest.mark.parametrize("page", [HTML, SWIPE], ids=["grid", "swipe"])


@pytest.mark.parametrize(
    "name",
    [
        "CANVAS_WIDTH",
        "SCREEN_HEIGHT",
        "TITLE_HEIGHT",
        "AREA_MARGIN",
        "CARD_MAX",
        "CARD_MIN",
        "GAP_RATIO",
    ],
)
def test_app_constants_match_the_server(name):
    match = re.search(rf"const {name} = ([\d.]+);", HTML)
    assert match, f"{name} missing from grid.html"
    assert float(match[1]) == pytest.approx(getattr(layout, name))


def test_app_card_aspect_matches_the_server():
    assert "const CARD_ASPECT = 140 / 81;" in HTML
    assert layout.CARD_ASPECT == pytest.approx(140 / 81)


@APPS
def test_the_app_loads_nothing_but_portraits(page):
    sources = set(re.findall(r"https://[\w.-]+", page))
    assert sources == {"https://cdn.steamstatic.com"}


@APPS
def test_the_handshake_sends_what_hosts_validate(page):
    """Hosts check ui/initialize against the ext-apps schema: appInfo, appCapabilities,
    protocolVersion. MCP's clientInfo in place of appInfo makes the host refuse the app."""
    init = page[page.index('request("ui/initialize"') :][:300]
    assert (
        "appInfo:" in init and "appCapabilities:" in init and "protocolVersion:" in init
    )
    assert "clientInfo" not in init


def test_the_swipe_verdicts_are_saved_as_model_context():
    """ext-apps' McpUiUpdateModelContextRequest: `content` as a ContentBlock array and
    `structuredContent` as an object (ADR 0011)."""
    call = SWIPE[SWIPE.index('request("ui/update-model-context"') :][:200]
    assert 'content: [{ type: "text", text }]' in call
    assert "structuredContent: { kept:" in call


def test_the_swipe_app_never_writes_into_the_chat_box():
    """ui/message puts text in the user's chat box on claude.ai (ADR 0011)."""
    assert "ui/message" not in SWIPE
