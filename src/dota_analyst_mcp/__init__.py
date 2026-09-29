"""The dota-analyst MCP server: live Stratz analysis and hero grids for the plugin (ADR 0001)."""

from importlib.metadata import version

# One version for the release: pyproject.toml, which plugin/.claude-plugin/plugin.json
# must match (tests/test_release.py) and CHANGELOG.md must describe.
__version__ = version("dota-analyst")
