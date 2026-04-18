.PHONY: deps env run check format typecheck test clean

PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON ?= $(VENV_DIR)/bin/python
ENV_FILE ?= .env
DEPS_STAMP ?= $(VENV_DIR)/.fronatend-deps-stamp

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV_DIR)
	$(VENV_PYTHON) -m ensurepip --upgrade

$(DEPS_STAMP): src/fronatend/requirements.txt | $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip --version >/dev/null 2>&1 || (rm -rf $(VENV_DIR) && $(PYTHON) -m venv $(VENV_DIR) && $(VENV_PYTHON) -m ensurepip --upgrade)
	$(VENV_PYTHON) -m pip install -r src/fronatend/requirements.txt
	touch $(DEPS_STAMP)

$(ENV_FILE): .env.example
	cp .env.example .env

deps: $(DEPS_STAMP)

env: $(ENV_FILE)

run: deps env
	PYTHONPATH=src/fronatend $(VENV_PYTHON) src/fronatend/app/main.py

check: typecheck test

format: deps
	$(VENV_PYTHON) -m black src/fronatend/app

typecheck: deps
	$(VENV_PYTHON) -m mypy --no-incremental src/fronatend/app

test: deps
	PYTHONPATH=src/fronatend $(VENV_PYTHON) -m pytest

clean:
	rm -rf $(VENV_DIR)
