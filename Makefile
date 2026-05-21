.PHONY: install test test-cov coverage-gate lint type check precommit clean import-graph

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

check: lint type test-cov coverage-gate import-graph

precommit:
	pre-commit run --all-files

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov coverage.xml build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
