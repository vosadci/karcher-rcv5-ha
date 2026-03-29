PYTHON ?= /opt/anaconda3/bin/python3
PIP    ?= $(PYTHON) -m pip

.PHONY: install test test-cov lint help

help:
	@echo "Targets:"
	@echo "  install    Install test dependencies"
	@echo "  test       Run the test suite"
	@echo "  test-cov   Run tests with coverage report"
	@echo "  lint       Run ruff linter over integration code"

install:
	$(PIP) install -r requirements_test.txt

test:
	$(PYTHON) -m pytest tests/ -v

test-cov:
	$(PYTHON) -m pytest tests/ -v \
		--cov=custom_components/karcher_home_robots \
		--cov-report=term-missing

lint:
	$(PYTHON) -m ruff check custom_components/karcher_home_robots/
