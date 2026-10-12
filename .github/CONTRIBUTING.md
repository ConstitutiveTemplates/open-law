# Contribute to the project

Contributions and issues are most welcome! All issues and pull requests are
handled through [GitHub](https://github.com/ConstitutiveTemplates/open-law/issues). Also, please check for any existing issues before
filing a new one. If you have a great idea but it involves big changes, please
file a ticket before making a pull request! We want to make sure you don't spend
your time coding something that might not fit the scope of the project.

## Security

Please do not open a public issue for security vulnerabilities. Report them
privately via the [Security Advisory workflow](https://github.com/ConstitutiveTemplates/open-law/security/advisories/new) — see [SECURITY.md](../SECURITY.md) for details.

## Issue or Discussion?

Github also offers [discussions](https://github.com/ConstitutiveTemplates/open-law/discussions) as a place to ask questions and share ideas. If
your issue is open ended and it is not obvious when it can be "closed", please
raise it as a discussion instead.

## Code Coverage

While 100% code coverage does not make a library bug-free, it significantly
reduces the number of easily caught bugs! Please make sure coverage remains the
same or is improved by a pull request!

## Developer Information

It is recommended that developers use a [vscode devcontainer](https://code.visualstudio.com/docs/devcontainers/containers). This repository contains configuration to set up a containerized development environment that suits its own needs.

This project was created using the [python-copier-template](https://github.com/ConstitutiveTemplates/open-law) for Python projects.

For more information on common tasks like setting up a developer environment, running the tests, and the lint workflow, see the template's [How-to guides](https://constitutivetemplates.github.io/daimonion/main/how-to/).

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
