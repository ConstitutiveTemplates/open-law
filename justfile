default:
    @just --list


# Check formatting and lint (ruff, check-only)

lint:
    uv run --locked ruff format --check . && uv run --locked ruff check .

# Auto-fix formatting, lint and typos (run before committing)

fix:
    uv run --locked ruff check --fix .
    uv run --locked ruff format . && uv run --locked typos -w .

# Run basedpyright + pyrefly + static analysis

type-check:
    uv run --locked basedpyright
    uv run --locked pyrefly check
    uv run --locked vulture src/open_law --min-confidence 80
    uv run --locked deptry .
    uv run --locked typos .

# Audit dependencies for known vulnerabilities (needs network)

audit:
    uv run --locked pip-audit

# Check dependency licenses comply with MIT (needs network)

license-check:
    uv run --locked pip-licenses --from=mixed --partial-match --fail-on=GPL

# Run tests with coverage

test:
    uv run --locked pytest --cov=src/open_law --cov-report term --cov-report xml:cov.xml

# Build documentation

docs:
    uv run --locked zensical build

# Serve documentation with live reload

docs-serve:
    uv run --locked zensical serve

# Run all quality checks

check: lint type-check test
