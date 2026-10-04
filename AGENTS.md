# Agent Guide for `open-law`

This file is for AI coding agents working in this repository. It states how
to run the checks and where edits belong. The human-facing contribution
guide is [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## Commands

The `just` task runner drives the common commands:

```sh
just fix            # auto-fix formatting and lint
just lint
just test
just check
```

Run `just fix` before committing to apply formatting
and lint fixes, then `just check` (or `lint` + `test`
+ `type-check` individually) before finishing a change.
The repo-hygiene checks (secrets, workflow linting, YAML validity,
conventional commit messages) run in CI, not as local hooks — the lint and
fix tasks work anywhere, including outside a git repository.

Type checking uses basedpyright plus `pyrefly`; `deptry`,
`vulture`, and `typos` also run as part of type-check.


Build the docs with `just docs`.

## Where to edit

- Application/package code: `src/open_law/`
- Country source adapters: `src/open_law/sources/` — one
  `SourceAdapter` subclass per jurisdiction, registered in that
  package's `__init__.py`; fetch through the shared fetcher, and check
  `docs/explanations/oss-evaluation.md` before adding a dependency or a
  new source channel
- Tests: `tests/` (offline; captured API responses live in
  `tests/fixtures/`)
- Docs: `README.md` and `docs/`

Keep 100% coverage where it exists; do not lower it.

## Web-fetching rules (Good-future charter)

- Every web fetch goes through `src/open_law/fetcher.py`
  — never call `requests.get` / `httpx.get` / `urlopen` directly
  (ruff `banned-api` fails the build).
- Read [CHARTER.md](CHARTER.md) before touching fetch code: robots.txt,
  1 req/s per host, disk cache, contactable User-Agent.
- Never generate CAPTCHA-solving helpers. If a site blocks bots, stop and
  ask the maintainer — do not bypass the protection.


## Commits and CI

- Use [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, ...); the commit-msg hook enforces it.
- CI runs lint, type-check, and tests on every push
 plus a docs build; keep all of them green.
