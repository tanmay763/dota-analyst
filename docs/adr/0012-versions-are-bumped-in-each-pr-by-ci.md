# Versions are bumped in each PR by CI, from the changelog notes

A PR that ships code says what changed under `[Unreleased]` in `CHANGELOG.md`, and CI does the rest. On every push to the PR, `scripts/release.py bump` takes the version on `main`, picks the part from the notes' headings (`### Removed` or a breaking note is major, or minor before 1.0.0; `### Added` is minor; the rest patch), writes the version to `pyproject.toml` and the plugin manifest, locks, and moves the notes under a dated section. CI runs the tests and lint on that tree and pushes the bump commit to the PR's branch. Merging tags the version and publishes the release.

The bump lands in the PR, not after the merge, because `main` only takes PRs: the "Protect main" ruleset has no bypass, so a bot couldn't push a bump commit to `main` either, and we don't want it to. Every version on `main` was reviewed in the PR that made it.

Docs- and CI-only PRs (`docs/`, `.github/`, root-level markdown, analysis reports) don't bump, because nothing users get changes. The plugin's skills and the served cookbook are markdown, but they are the product, so they bump.

The bump is computed from `main`'s version every time, so pushing again never bumps twice; notes added later join the same section. Two open PRs both aim at the next version, and whichever merges second resolves the conflict by taking `main`'s versions and returning its notes to `[Unreleased]`.

## Considered Options

- **Bump on merge, by a bot pushing to `main`**: needs a bypass in the ruleset, and puts unreviewed commits on `main`.
- **A release PR opened by a bot after merges (release-please style)**: a second PR per release, and bot-opened PRs don't start other workflows with the default token.
- **Bump by hand** (what we did until 0.1.2): easy to forget one of the two version files or the lock, and the part is a judgement made twice, in the notes and in the number.
