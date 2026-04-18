# HackKU-2026

## Frontend Setup (macOS)

The repository currently contains the Go engine in `src/engine` and a PySide6 desktop frontend in `frontend/`.
These steps stay on the Python desktop side only.

### 1. Create a virtual environment

```bash
cd /Users/Alex.Phibbs/Documents/Codex/2026-04-17-set-up-the-local-development-environment/HackKU-2026
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2. Install frontend dependencies

```bash
pip install -r frontend/requirements.txt
```

Installed packages:

- `PySide6` for the desktop shell and UI widgets
- `qasync` for running Qt and `asyncio` together
- `httpx` for localhost HTTP calls to the backend
- `websockets` for realtime room events and chat
- `pydantic` for structured config and models
- `python-dotenv` for local environment variables
- `pytest`, `black`, `isort`, and `mypy` for basic developer tooling

### 3. Configure local backend endpoints

```bash
cp .env.example .env
```

Defaults:

- HTTP API: `http://127.0.0.1:8080`
- WebSocket API: `ws://127.0.0.1:8080/ws`

### 4. Run the desktop frontend

```bash
python frontend/app/main.py
```

Or use:

```bash
make run
```

The starter UI includes:

- a central video placeholder panel
- a room sidebar
- a chat panel
- a participant list
- a file sharing placeholder panel

This layout is intended to be hackathon-friendly and easy to extend as backend endpoints solidify.

## VS Code On macOS

Yes, VS Code is a good fit for this project on Mac.
The repo now includes shared VS Code config in `.vscode/` for the Python frontend workflow.

Included setup:

- interpreter path pointed at `.venv/bin/python`
- format-on-save with Black
- import sorting with isort
- basic mypy integration
- pytest discovery
- a launch profile for the PySide6 frontend
- tasks to create the venv, install deps, run the app, and run tests
- recommended extensions for Python and TOML support

Suggested first-run flow in VS Code:

1. Open the repository folder in VS Code.
2. Let VS Code install the recommended extensions when prompted.
3. Run the task `Python: Create venv` if `.venv` does not exist yet.
4. Run the task `Python: Install frontend deps`.
5. Copy `.env.example` to `.env`.
6. Start the app with the `Run Moovie Night Frontend` launch config or the `Frontend: Run app` task.

## Quick Commands

Use the project `Makefile` for the common frontend workflow:

```bash
make deps
make env
make run
```

There is also a short run guide in `RUNNING.md`.
