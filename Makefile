.PHONY: deps env run check format typecheck test clean

PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON ?= $(VENV_DIR)/bin/python
ENV_FILE ?= .env
DEPS_STAMP ?= $(VENV_DIR)/.frontend-deps-stamp

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV_DIR)

$(DEPS_STAMP): frontend/requirements.txt | $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install -r frontend/requirements.txt
	touch $(DEPS_STAMP)

$(ENV_FILE): .env.example
	cp .env.example .env

deps: $(DEPS_STAMP)

env: $(ENV_FILE)

run: deps env
	$(VENV_PYTHON) frontend/app/main.py

check: typecheck test

format: deps
	$(VENV_PYTHON) -m black frontend/app

typecheck: deps
	$(VENV_PYTHON) -m mypy --no-incremental frontend/app

test: deps
	$(VENV_PYTHON) -m pytest

clean:
	rm -rf $(VENV_DIR)
