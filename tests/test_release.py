"""The release has one version, and the changelog describes it."""

import json
import tomllib
from pathlib import Path

import dota_analyst_mcp

ROOT = Path(__file__).parents[1]


def test_the_plugin_and_the_server_share_one_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads((ROOT / "plugin/.claude-plugin/plugin.json").read_text())[
        "version"
    ]
    assert plugin == project == dota_analyst_mcp.__version__


def test_the_changelog_has_an_entry_for_this_version():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## [{dota_analyst_mcp.__version__}] - " in changelog
