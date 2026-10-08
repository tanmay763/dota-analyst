"""The release has one version, and the changelog describes it."""

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

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


# --- scripts/release.py -------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [Unreleased]

- Something not released yet.

## [0.2.0] - 2026-10-01

### Added

- A thing.

## [0.1.0] - 2026-09-29

- The first release.

[Unreleased]: https://example.com/compare/v0.2.0...HEAD
[0.2.0]: https://example.com/releases/tag/v0.2.0
"""


def test_release_notes_are_one_changelog_section():
    assert release.changelog_notes(CHANGELOG, "0.2.0") == "### Added\n\n- A thing."
    assert release.changelog_notes(CHANGELOG, "0.1.0") == "- The first release."


def test_release_notes_need_a_dated_nonempty_section():
    with pytest.raises(release.ReleaseError, match="no"):
        release.changelog_notes(CHANGELOG, "0.3.0")
    with pytest.raises(release.ReleaseError, match="empty"):
        release.changelog_notes(
            "## [1.0.0] - 2026-01-01\n\n## [0.9.0] - 2025-12-01\n- x\n", "1.0.0"
        )


def test_this_repos_changelog_has_notes_for_its_version():
    assert release.changelog_notes(
        (ROOT / "CHANGELOG.md").read_text(), dota_analyst_mcp.__version__
    )
