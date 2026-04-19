.PHONY: deps env run frontend frontend2 backend dev dev-dual stop-backend check format typecheck test clean

PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON ?= $(VENV_DIR)/bin/python
ENV_FILE ?= .env
DEPS_STAMP ?= $(VENV_DIR)/.fronatend-deps-stamp
ENGINE_DIR ?= src/engine
PIPEWIRE_AVAILABLE := $(shell pkg-config --exists libpipewire-0.3 && echo 1 || echo 0)
ENGINE_GO_TAGS ?= $(if $(filter 1,$(PIPEWIRE_AVAILABLE)),pipewire,)

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

frontend: deps env
	PYTHONPATH=src/fronatend $(VENV_PYTHON) src/fronatend/app/main.py

frontend2: deps env
	PYTHONPATH=src/fronatend $(VENV_PYTHON) src/fronatend/app/main.py

run: frontend

backend:
	@echo "Starting backend (ENGINE_GO_TAGS='$(ENGINE_GO_TAGS)')"
	cd $(ENGINE_DIR) && go run $(if $(ENGINE_GO_TAGS),-tags '$(ENGINE_GO_TAGS)',) .

dev: deps env
	@set -eu; \
	echo "Starting dev stack (ENGINE_GO_TAGS='$(ENGINE_GO_TAGS)')"; \
	if ss -ltn '( sport = :8080 )' | grep -q ':8080'; then \
		echo "Port 8080 is already in use. Run 'make stop-backend' first."; \
		exit 1; \
	fi; \
	BACKEND_PID=""; \
	cleanup() { \
		if [ -n "$$BACKEND_PID" ] && kill -0 "$$BACKEND_PID" 2>/dev/null; then \
			kill -TERM -- "-$$BACKEND_PID" 2>/dev/null || kill -TERM "$$BACKEND_PID" 2>/dev/null || true; \
			wait "$$BACKEND_PID" 2>/dev/null || true; \
		fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	setsid sh -c "cd $(ENGINE_DIR) && ENGINE_TX_WIDTH=1280 ENGINE_TX_HEIGHT=720 ENGINE_TX_FPS=24 ENGINE_TX_QUALITY=veryfast exec go run $(if $(ENGINE_GO_TAGS),-tags $(ENGINE_GO_TAGS),) ." & \
	BACKEND_PID=$$!; \
	sleep 1; \
	if ! kill -0 "$$BACKEND_PID" 2>/dev/null; then \
		echo "Backend exited during startup."; \
		exit 1; \
	fi; \
	PYTHONPATH=src/fronatend $(VENV_PYTHON) src/fronatend/app/main.py

dev-dual: deps env
	@set -eu; \
	echo "Starting dual-client dev stack (ENGINE_GO_TAGS='$(ENGINE_GO_TAGS)')"; \
	if ss -ltn '( sport = :8080 )' | grep -q ':8080'; then \
		echo "Port 8080 is already in use. Run 'make stop-backend' first."; \
		exit 1; \
	fi; \
	BACKEND_PID=""; \
	WATCHER_PID=""; \
	cleanup() { \
		if [ -n "$$WATCHER_PID" ] && kill -0 "$$WATCHER_PID" 2>/dev/null; then \
			kill -TERM "$$WATCHER_PID" 2>/dev/null || true; \
			wait "$$WATCHER_PID" 2>/dev/null || true; \
		fi; \
		if [ -n "$$BACKEND_PID" ] && kill -0 "$$BACKEND_PID" 2>/dev/null; then \
			kill -TERM -- "-$$BACKEND_PID" 2>/dev/null || kill -TERM "$$BACKEND_PID" 2>/dev/null || true; \
			wait "$$BACKEND_PID" 2>/dev/null || true; \
		fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	setsid sh -c "cd $(ENGINE_DIR) && ENGINE_TX_WIDTH=1280 ENGINE_TX_HEIGHT=720 ENGINE_TX_FPS=24 ENGINE_TX_QUALITY=veryfast exec go run $(if $(ENGINE_GO_TAGS),-tags $(ENGINE_GO_TAGS),) ." & \
	BACKEND_PID=$$!; \
	sleep 1; \
	if ! kill -0 "$$BACKEND_PID" 2>/dev/null; then \
		echo "Backend exited during startup."; \
		exit 1; \
	fi; \
	PYTHONPATH=src/fronatend $(VENV_PYTHON) src/fronatend/app/main.py & \
	WATCHER_PID=$$!; \
	echo ""; \
	echo "Dual test ready:"; \
	echo "  1) Host window: create room + start screen share"; \
	echo "  2) Watcher window: join with ROOM@host:port from host invite"; \
	echo "  3) Close host window (foreground) to stop all launched processes"; \
	echo ""; \
	PYTHONPATH=src/fronatend $(VENV_PYTHON) src/fronatend/app/main.py

stop-backend:
	@set -eu; \
	PIDS=$$(ss -ltnp '( sport = :8080 )' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true); \
	if [ -z "$$PIDS" ]; then \
		echo "No backend process is listening on :8080."; \
		exit 0; \
	fi; \
	echo "Stopping backend pids: $$PIDS"; \
	kill $$PIDS 2>/dev/null || true

check: typecheck test

format: deps
	$(VENV_PYTHON) -m black src/fronatend/app

typecheck: deps
	$(VENV_PYTHON) -m mypy --no-incremental src/fronatend/app

test: deps
	PYTHONPATH=src/fronatend $(VENV_PYTHON) -m pytest

clean:
	rm -rf $(VENV_DIR)
