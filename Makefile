.PHONY: install test test-cov coverage-gate lint type check precommit clean import-graph \
        front front-install mutation

PY ?= python3
PKG := custom_components/karcher_home_robots

install:
	$(PY) -m pip install -e '.[test,dev]'
	pre-commit install

test:
	$(PY) -m pytest tests/ -v

# Run pytest with coverage; never sets --cov-fail-under directly. The
# phase-graduated gate is enforced separately by `coverage-gate`,
# which reads [tool.karcher].phase from pyproject.toml.
test-cov:
	$(PY) -m pytest tests/ --cov=$(PKG) --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=html

coverage-gate:
	$(PY) tests/tools/coverage_gate.py

lint:
	$(PY) -m ruff check $(PKG) tests
	$(PY) -m ruff format --check $(PKG) tests

type:
	$(PY) -m mypy --strict $(PKG)

import-graph:
	$(PY) tests/tools/check_imports.py

# Frontend (Lovelace card) — a SEPARATE npm/node toolchain, not the Python venv.
# `front` mirrors the CI frontend job (eslint + vitest). Run `make front-install`
# once first. Intentionally NOT part of `check` so backend-only work needs no node.
front-install:
	npm ci

front:
	npm run check

check: lint type test-cov coverage-gate import-graph

# On-request only — NOT part of `check`, NOT run in CI. Requires the
# `mutation` extra (`pip install -e .[mutation]`). Scope (source_paths /
# only_mutate) lives in pyproject.toml [tool.mutmut]. See tests/README.md
# "Mutation testing" for how to read the results.
mutation:
	$(PY) -m mutmut run
	$(PY) -m mutmut results

precommit:
	pre-commit run --all-files

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
