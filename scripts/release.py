"""Bump the version in a PR, and tag and publish the GitHub release once it's merged.

    make bump            # in a PR: next version from the [Unreleased] notes (ADR 0012)
    make release-check   # every release check, no tag and no release
    make release         # the checks, then tag vX.Y.Z, push it, publish the GitHub release

CI runs `bump` on every PR and `--if-new` on every merge to main, so neither is usually
run by hand (docs/deployment.md, "Releasing"). Deploying is `make deploy`. Standard
library only.
"""

import argparse
import datetime
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = "pyproject.toml"
PLUGIN = "plugin/.claude-plugin/plugin.json"
# Keep a Changelog's headings, in its order; others follow in the order they appear.
HEADINGS = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]
SECTION = re.compile(
    r"^## \[(?P<name>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?[ \t]*$", re.MULTILINE
)
LINKS = re.compile(r"^\[[^\]]+\]: ", re.MULTILINE)


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
    project = tomllib.loads((ROOT / PYPROJECT).read_text())["project"]["version"]
    plugin = json.loads((ROOT / PLUGIN).read_text())["version"]
    if project != plugin:
        raise ReleaseError(
            f"pyproject.toml says {project} but plugin.json says {plugin}"
        )
    return project


# --- bumping, in a PR ----------------------------------------------------------------------


def ships_nothing(paths: list[str]) -> bool:
    """Whether a change touches only documentation and CI, which ship in neither the plugin
    nor the server. Shipped markdown (plugin skills, the served cookbook) isn't documentation."""
    return all(
        path.startswith(("docs/", ".github/"))
        or ("/" not in path and path.endswith(".md"))
        or (path.startswith("analyses/") and path.endswith(".md"))
        for path in paths
    )


def parse_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise ReleaseError(f"{version!r} isn't a MAJOR.MINOR.PATCH version")
    return int(match[1]), int(match[2]), int(match[3])


def bump_part(notes: str, version: str) -> str:
    """major, minor or patch, from the notes' headings. A breaking change is major, or
    minor before 1.0.0 (the changelog's preamble); an addition is minor; the rest patch."""
    if re.search(r"^### Removed\b|\*\*Breaking\b", notes, re.MULTILINE | re.IGNORECASE):
        return "major" if parse_version(version)[0] >= 1 else "minor"
    if re.search(r"^### Added\b", notes, re.MULTILINE):
        return "minor"
    return "patch"


def next_version(version: str, part: str) -> str:
    major, minor, patch = parse_version(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _sections(text: str) -> list[tuple[str, int, int, int]]:
    """(name, header start, body start, body end) for each `## [name]` section."""
    links = LINKS.search(text)
    end_of_sections = links.start() if links else len(text)
    headers = list(SECTION.finditer(text))
    return [
        (
            m["name"],
            m.start(),
            m.end(),
            headers[i + 1].start() if i + 1 < len(headers) else end_of_sections,
        )
        for i, m in enumerate(headers)
    ]


def merge_notes(bodies: list[str]) -> str:
    """Several sections' notes as one, with each `### Heading`'s items together."""
    groups: dict[str, list[str]] = {}
    for body in bodies:
        # re.split keeps the captured headings: [loose, heading, items, heading, items...]
        parts = re.split(r"^### +(.+?)[ \t]*$", body.strip(), flags=re.MULTILINE)
        loose, rest = parts[0], parts[1:]
        if loose.strip():
            groups.setdefault("", []).append(loose.strip())
        for heading, items in zip(rest[::2], rest[1::2], strict=True):
            if items.strip():
                groups.setdefault(heading.strip(), []).append(items.strip())
    order = [""] + [h for h in HEADINGS if h in groups]
    order += [h for h in groups if h not in order]
    chunks = []
    for heading in order:
        if heading not in groups:
            continue
        items = "\n".join(groups[heading])
        chunks.append(items if not heading else f"### {heading}\n\n{items}")
    return "\n\n".join(chunks)


def pending_notes(changelog: str, base: str) -> str:
    """The notes this change adds: [Unreleased] and any section above the base version,
    left by an earlier bump of the same PR. The earlier notes come first."""
    base_version = parse_version(base)
    bodies = [
        changelog[start:end]
        for name, _, start, end in _sections(changelog)
        if name == "Unreleased"
        or (re.fullmatch(r"\d+\.\d+\.\d+", name) and parse_version(name) > base_version)
    ]
    return merge_notes(bodies[::-1])  # sections are newest first


def rewrite_changelog(changelog: str, base: str, target: str, today: str) -> str:
    """[Unreleased] and any pending sections become one `## [target] - today` section,
    with its compare link. Running it again on its own output changes nothing."""
    notes = pending_notes(changelog, base)
    if not notes:
        raise ReleaseError("CHANGELOG.md has no notes under [Unreleased]: add them")
    sections = _sections(changelog)
    unreleased = next((s for s in sections if s[0] == "Unreleased"), None)
    if unreleased is None:
        raise ReleaseError("CHANGELOG.md has no '## [Unreleased]' section")
    base_version = parse_version(base)
    kept = [
        s
        for s in sections
        if s[0] != "Unreleased"
        and not (
            re.fullmatch(r"\d+\.\d+\.\d+", s[0]) and parse_version(s[0]) > base_version
        )
    ]
    head = changelog[: unreleased[1]]
    body = "".join(changelog[s[1] : s[3]] for s in kept)
    links = changelog[kept[-1][3] if kept else unreleased[3] :]
    link = re.search(r"^\[Unreleased\]: (\S+)/compare/\S+$", links, re.MULTILINE)
    if link is None:
        raise ReleaseError(
            "CHANGELOG.md has no '[Unreleased]: <repo>/compare/...' link"
        )
    repo = link[1]
    stale = {
        name
        for name, *_ in sections
        if re.fullmatch(r"\d+\.\d+\.\d+", name) and parse_version(name) > base_version
    }
    lines = [
        line
        for line in links.splitlines(keepends=True)
        if not any(line.startswith(f"[{v}]: ") for v in stale)
    ]
    links = "".join(lines).replace(
        link[0],
        f"[Unreleased]: {repo}/compare/v{target}...HEAD\n"
        f"[{target}]: {repo}/compare/v{base}...v{target}",
        1,
    )
    return (
        f"{head}## [Unreleased]\n\n## [{target}] - {today}\n\n{notes}\n\n{body}{links}"
    )


def set_version(path: Path, pattern: str, version: str) -> None:
    """Replace the one version line `pattern` matches; its group 1 is kept before it."""
    text = path.read_text()
    new, count = re.subn(
        pattern, rf"\g<1>{version}\g<2>", text, count=1, flags=re.MULTILINE
    )
    if count != 1:
        raise ReleaseError(f"no version line in {path.relative_to(ROOT)}")
    path.write_text(new)


def bump(base_ref: str) -> str:
    """Bump this branch's version from `base_ref`'s by its changelog notes; returns what
    happened. Docs- and CI-only changes aren't bumped (ADR 0012)."""
    paths = git("diff", "--name-only", f"{base_ref}...HEAD").splitlines()
    if ships_nothing(paths):
        return "docs- or CI-only change: no version bump"
    base = tomllib.loads(git("show", f"{base_ref}:{PYPROJECT}"))["project"]["version"]
    changelog_path = ROOT / "CHANGELOG.md"
    changelog = changelog_path.read_text()
    notes = pending_notes(changelog, base)
    if not notes:
        raise ReleaseError(
            "this change ships code but CHANGELOG.md has no notes under [Unreleased]: "
            "add them, and the version is bumped from them"
        )
    part = bump_part(notes, base)
    target = next_version(base, part)
    today = datetime.datetime.now(datetime.UTC).date().isoformat()  # as CI dates it
    changelog_path.write_text(rewrite_changelog(changelog, base, target, today))
    set_version(ROOT / PYPROJECT, r'^(version = ")[^"]+(")', target)
    set_version(ROOT / PLUGIN, r'^(  "version": ")[^"]+(")', target)
    subprocess.run(["uv", "lock", "--quiet"], cwd=ROOT, check=True)
    return f"{base} -> {target} ({part})"


# --- releasing, once merged -----------------------------------------------------------------


def tagged(tag: str) -> bool:
    return bool(
        git("tag", "--list", tag)
        or git("ls-remote", "--tags", "origin", f"refs/tags/{tag}")
    )


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
    parser.add_argument(
        "--if-new",
        action="store_true",
        help="do nothing, successfully, when this version is already tagged",
    )
    commands = parser.add_subparsers(dest="command")
    bumper = commands.add_parser("bump", help="bump the version from the changelog")
    bumper.add_argument("--base", default="origin/main", help="the branch merged into")
    args = parser.parse_args()
    if args.command == "bump":
        try:
            print(f"bump: {bump(args.base)}")
        except ReleaseError as exc:
            print(f"bump: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        version = release_version()
        if args.if_new:
            git("fetch", "--quiet", "origin", "--tags")
            if tagged(f"v{version}"):
                print(f"release: v{version} is already tagged; nothing to release")
                return 0
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
