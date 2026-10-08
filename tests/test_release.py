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


# --- bumping (ADR 0012) -------------------------------------------------------------------


@pytest.mark.parametrize(
    "paths, nothing",
    [
        (["docs/deployment.md", "docs/adr/0012-x.md", "README.md", "CONTEXT.md"], True),
        (["CHANGELOG.md", "analyses/ti2026/ti2026_2026-09-30.md"], True),
        ([], True),
        ([".github/workflows/ci.yml", "docs/deployment.md"], True),
        ([".github/workflows/ci.yml", "scripts/release.py"], False),
        (["plugin/skills/hero-grid-builder/SKILL.md"], False),  # shipped in the plugin
        ([".claude/skills/stratz-analysis/references/cookbook.md"], False),  # served
        (["plugin/README.md"], False),
        (["docs/deployment.md", "src/dota_analyst_mcp/app.py"], False),
        (["analyses/ti2026/ti2026_report.py"], False),
    ],
)
def test_documentation_and_ci_ship_nothing(paths, nothing):
    assert release.ships_nothing(paths) is nothing


@pytest.mark.parametrize(
    "notes, version, part",
    [
        ("### Added\n\n- A tool.", "0.1.2", "minor"),
        ("### Changed\n\n- Wording.\n\n### Fixed\n\n- A bug.", "0.1.2", "patch"),
        ("- A loose note.", "1.4.0", "patch"),
        ("### Removed\n\n- A tool.", "0.1.2", "minor"),  # breaking before 1.0
        ("### Removed\n\n- A tool.", "1.4.0", "major"),
        ("### Changed\n\n- **Breaking:** a tool's arguments.", "1.4.0", "major"),
        ("### Added\n\n- A.\n\n### Removed\n\n- B.", "2.0.1", "major"),
    ],
)
def test_the_notes_pick_the_part_to_bump(notes, version, part):
    assert release.bump_part(notes, version) == part


def test_next_version_resets_the_lower_parts():
    assert release.next_version("1.4.2", "major") == "2.0.0"
    assert release.next_version("1.4.2", "minor") == "1.5.0"
    assert release.next_version("1.4.2", "patch") == "1.4.3"
    with pytest.raises(release.ReleaseError, match="MAJOR.MINOR.PATCH"):
        release.next_version("1.4", "patch")


def test_unreleased_notes_become_the_new_versions_section():
    bumped = release.rewrite_changelog(CHANGELOG, "0.2.0", "0.2.1", "2026-10-08")
    assert bumped.startswith(
        "# Changelog\n\n## [Unreleased]\n\n## [0.2.1] - 2026-10-08\n\n"
        "- Something not released yet.\n\n## [0.2.0] - 2026-10-01\n"
    )
    assert bumped.endswith(
        "[Unreleased]: https://example.com/compare/v0.2.1...HEAD\n"
        "[0.2.1]: https://example.com/compare/v0.2.0...v0.2.1\n"
        "[0.2.0]: https://example.com/releases/tag/v0.2.0\n"
    )
    assert release.changelog_notes(bumped, "0.2.1") == "- Something not released yet."
    # CI bumps on every push to a PR: a second run changes nothing...
    assert release.rewrite_changelog(bumped, "0.2.0", "0.2.1", "2026-10-08") == bumped


def test_notes_added_after_a_bump_join_its_section_by_heading():
    first = release.rewrite_changelog(
        CHANGELOG.replace("- Something not released yet.", "### Fixed\n\n- A bug."),
        "0.2.0",
        "0.2.1",
        "2026-10-08",
    )
    later = first.replace(
        "## [Unreleased]\n",
        "## [Unreleased]\n\n### Added\n\n- A tool.\n\n### Fixed\n\n- Another bug.\n",
    )
    part = release.bump_part(release.pending_notes(later, "0.2.0"), "0.2.0")
    again = release.rewrite_changelog(later, "0.2.0", "0.3.0", "2026-10-09")
    assert part == "minor"
    assert release.changelog_notes(again, "0.3.0") == (
        "### Added\n\n- A tool.\n\n### Fixed\n\n- A bug.\n- Another bug."
    )
    assert "[0.2.1]" not in again and "## [0.2.1]" not in again
    assert "[0.3.0]: https://example.com/compare/v0.2.0...v0.3.0\n" in again


def test_a_bump_needs_notes():
    empty = CHANGELOG.replace("- Something not released yet.\n\n", "")
    with pytest.raises(release.ReleaseError, match="no notes under"):
        release.rewrite_changelog(empty, "0.2.0", "0.2.1", "2026-10-08")


def test_version_lines_are_replaced_in_place(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "x"\nversion = "0.1.2"\n\n[tool.x]\nversion = "9"\n'
    )
    release.set_version(pyproject, r'^(version = ")[^"]+(")', "0.2.0")
    assert pyproject.read_text() == (
        '[project]\nname = "x"\nversion = "0.2.0"\n\n[tool.x]\nversion = "9"\n'
    )
