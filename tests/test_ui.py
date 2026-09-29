"""The hero grid app draws cards with the same geometry the server places them with."""

import re
from pathlib import Path

import pytest

from dota_analyst_mcp import layout

HTML = (Path(layout.__file__).parent / "ui" / "grid.html").read_text()


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


def test_the_app_loads_nothing_but_portraits():
    sources = set(re.findall(r"https://[\w.-]+", HTML))
    assert sources == {"https://cdn.steamstatic.com"}


def test_the_handshake_sends_what_hosts_validate():
    """Hosts check ui/initialize against the ext-apps schema: appInfo, appCapabilities,
    protocolVersion. MCP's clientInfo in place of appInfo makes the host refuse the app."""
    init = HTML[HTML.index('request("ui/initialize"') :][:300]
    assert (
        "appInfo:" in init and "appCapabilities:" in init and "protocolVersion:" in init
    )
    assert "clientInfo" not in init
