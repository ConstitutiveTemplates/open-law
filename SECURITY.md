# Security Policy

open-law fetches legislation from official publishers over the network.
Its security-sensitive surface includes the shared fetcher
(`src/open_law/fetcher.py`), the parsers that read fetched documents, the
rest of the package code under `src/open_law/`, the CI/CD (`.github/`), and
the dependency manifest (`pyproject.toml` / lockfile).

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities. Instead,
report them privately through GitHub's Security Advisory workflow:

1. Go to <https://github.com/politeuma/open-law/security/advisories/new>
2. Provide a clear description of the vulnerability, including:
   - the affected file(s);
   - the impact (e.g. secrets exposed, command injection);
   - a minimal reproduction, where possible.

If you cannot use the advisory form, email the maintainer(s) (see the
[GitHub profile](https://github.com/kasi-x) for contact details).

## Response

You will receive an acknowledgement of your report. We aim to:

- triage the report within **7 days**;
- keep you informed as a fix is prepared;
- credit you for the discovery (unless you prefer to stay anonymous).

## Scope

| In scope | Out of scope |
|---|---|
| This repository's source, CI/CD and dependencies | Vulnerabilities in third-party dependencies already tracked by renovate / dependabot alerts |
| The `open-law` CLI and Python package, including how they handle fetched content | The legislation websites and APIs open-law reads from (report those to their operators) |
