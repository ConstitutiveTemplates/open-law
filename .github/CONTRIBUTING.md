# Contribute to the project

Contributions and issues are most welcome! All issues and pull requests are
handled through [GitHub](https://github.com/politeuma/open-law/issues). Also, please check for any existing issues before
filing a new one. If you have a great idea but it involves big changes, please
file a ticket before making a pull request! We want to make sure you don't spend
your time coding something that might not fit the scope of the project.

## Security

Please do not open a public issue for security vulnerabilities. Report them
privately via the [Security Advisory workflow](https://github.com/politeuma/open-law/security/advisories/new) — see [SECURITY.md](../SECURITY.md) for details.

## Issue or Discussion?

Github also offers [discussions](https://github.com/politeuma/open-law/discussions) as a place to ask questions and share ideas. If
your issue is open ended and it is not obvious when it can be "closed", please
raise it as a discussion instead.

## Code Coverage

While 100% code coverage does not make a library bug-free, it significantly
reduces the number of easily caught bugs! Please make sure coverage remains the
same or is improved by a pull request!

## Development setup

Prerequisites: Python 3.11 or later and [uv](https://docs.astral.sh/uv/).
A [vscode devcontainer](https://code.visualstudio.com/docs/devcontainers/containers)
configuration is also included if you prefer a containerized environment.

```sh
git clone https://github.com/politeuma/open-law.git
cd open-law
uv sync                      # create .venv and install everything (incl. dev deps)
```

From a clone, prefix CLI commands with `uv run` (for example
`uv run open-law sources`). Live fetches need `FETCHER_CONTACT` set to an
address site operators can reach; the test suite runs fully offline.

### Environment variables

Copy the example file and adjust the values:

```sh
cp .env.example .env
```

`.env` is loaded automatically by [direnv](https://direnv.net) (see `.envrc`)
and by the Docker stack; it is git-ignored, so never commit real secrets.

### Lint, type-check and test

The project uses [Just](https://just.systems) to drive the common commands:

```sh
just fix      # auto-fix formatting and lint (run before committing)
just lint
just test
just check    # lint + type-check + test
```

Repo hygiene (secret scanning, workflow linting, conventional commit
messages) is enforced in CI. See [AGENTS.md](../AGENTS.md) for AI-agent
guidance (commands, edit scope, commit rules).

### Updating from the template

This project was created from the
[architekton-py](https://github.com/politeuma/architekton-py) template and
records its answers in `.copier-answers.yml`, so it can receive template
improvements later. To update:

```sh
uvx copier update --trust --defaults
```

Resolve any conflicts, run `just fix` and `just check`, then commit. See the
template's
[adopt/update guide](https://politeuma.github.io/architekton-py/main/how-to/update-template/)
for the conflict-resolution workflow.

## Language

English is the canonical language of this project's docs; Japanese
versions, where they exist, are translations kept to the same standard.
Write new docs in English first.

## Blast radius

What a change touches decides what must pass before the PR. The table
below is what *you* run locally — the cheapest tier that covers the
blast radius, never the whole suite.

| Change scope | Required verification |
| --- | --- |
| Docs only (`README.md`, `docs/*.md`) | `just lint` — formatting and lint must be caught locally |
| Source adapter (`src/open_law/sources/*.py`) | `just test` for the touched adapter's test module (e.g. `uv run pytest tests/test_sources_uk.py -q`), plus `uv run open-law sources` to confirm the registry still loads |
| Fetcher / models (`src/open_law/fetcher.py`, `src/open_law/models.py`) | `just check` — shared plumbing affects every adapter, so run lint, type-check and the full test suite |
| Other source changes (`src/open_law/*.py`, `tests/`) | `just check` — lint, type-check and tests |

## Not legal advice

politeuma records what legal sources say and which engineering practices
they support. It does not decide whether your product complies with any
law, and using it does not make anything compliant. Sources can go out of
date or be misread, so every rule shows its sources and the date it was
last checked. Contributors and reviewers share their understanding in good
faith; their contributions are not legal advice to you or anyone else.
