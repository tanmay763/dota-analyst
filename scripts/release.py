"""Tag and publish the GitHub release for the version in pyproject.toml.

    make release-check   # every check, no tag and no release
    make release         # the checks, then tag vX.Y.Z, push it, publish the GitHub release

Bumping the version and writing the changelog are done by hand before this, and deploying
is `make deploy` (docs/deployment.md, "Releasing"). This does the mechanical part only,
from a clean `main` that matches `origin/main`. Standard library only.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(Exception):
    pass


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def changelog_notes(changelog: str, version: str) -> str:
    """The body of the `## [version] - YYYY-MM-DD` section, up to the next section."""
    match = re.search(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}[ \t]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ReleaseError(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section")
    notes = match.group(1).strip()
    if not notes:
        raise ReleaseError(f"CHANGELOG.md's section for {version} is empty")
    return notes


def release_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads((ROOT / "plugin/.claude-plugin/plugin.json").read_text())[
        "version"
    ]
    if project != plugin:
        raise ReleaseError(
            f"pyproject.toml says {project} but plugin.json says {plugin}"
        )
    return project


def problems(version: str) -> list[str]:
    """Every reason not to release now; empty when it's safe."""
    found = []
    branch = git("branch", "--show-current")
    if branch != "main":
        found.append(f"on branch {branch!r}, not main")
    if git("status", "--porcelain"):
        found.append("the working tree has uncommitted changes")
    git("fetch", "--quiet", "origin", "main", "--tags")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        found.append("HEAD isn't origin/main: pull or push first")
    tag = f"v{version}"
    if git("tag", "--list", tag):
        found.append(f"tag {tag} already exists locally")
    if git("ls-remote", "--tags", "origin", f"refs/tags/{tag}"):
        found.append(f"tag {tag} already exists on origin")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="check only; don't tag or publish"
    )
    args = parser.parse_args()
    try:
        version = release_version()
        notes = changelog_notes((ROOT / "CHANGELOG.md").read_text(), version)
    except ReleaseError as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1
    found = problems(version)
    if found:
        print(f"release: not releasing v{version}:", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    subprocess.run(["make", "test", "lint"], cwd=ROOT, check=True)
    tag = f"v{version}"
    if args.dry_run:
        print(
            f"release: ready to tag {tag} and publish the release with these notes:\n"
        )
        print(notes)
        return 0
    git("tag", "-a", tag, "-m", f"dota-analyst {version}")
    git("push", "origin", tag)
    subprocess.run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--verify-tag",
            "--title",
            f"dota-analyst {version}",
            "--notes-file",
            "-",
        ],
        cwd=ROOT,
        input=notes,
        text=True,
        check=True,
    )
    print(f"release: published {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
