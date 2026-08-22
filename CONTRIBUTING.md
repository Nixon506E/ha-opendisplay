# Contributing

Feature requests and bug reports are welcome, and pull requests are encouraged.
The [Discord server](https://discord.com/invite/tw48NCrRxH) is the place to
discuss ideas or get help.

## Translations

English is written by hand; every other language is filled in by
`.github/workflows/translate.yml`. Corrections are welcome and are never
overwritten, which the README explains.

If you need to run or change the tooling, `scripts/translate.py` documents
itself: its module docstring covers provider selection, why `en.json` rather
than `strings.json` is the source of truth, and how manual edits are protected.
`--dry-run` previews a run without writing. `scripts/verify_translations.py`
checks the files on disk and is what CI runs.

## Commits and releases

Commit messages follow [Conventional Commits][cc]. Releases are cut
automatically by release-please on every push to `main`, so the commit type
decides both the next version and what the release notes say.

| type | version | in the notes |
|---|---|---|
| `feat` | minor | yes |
| `fix` | patch | yes |
| `perf`, `revert` | none | yes |
| `chore`, `refactor`, `docs`, `test`, `ci`, `build`, `style` | none | no |

A `!` after the type, or a `BREAKING CHANGE:` footer, bumps the major version.

Release notes are rendered on the HACS page, so they are written for someone
deciding whether to install, not for someone reading the diff. That is why the
internal types are hidden.

**Bumping `py-opendisplay` or `odl-renderer` is a `fix:`, not a `chore:`** (or a
`feat:` if the bump adds capability). Those are `manifest.json` requirements
that Home Assistant installs at runtime, so the bump changes what users
actually get. As a `chore:` it would neither appear in the release notes nor
trigger the release that ships it, and would sit unreleased until some
unrelated change landed.

Pull requests are merged with a merge commit, so every commit on the branch
lands on `main` and each one's type is read. Keep them all conventional, not
just the pull request title, which is not read at all.

[cc]: https://www.conventionalcommits.org/
