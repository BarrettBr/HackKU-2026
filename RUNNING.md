# Running The Frontend

These commands work for both macOS and Linux.

## First-time setup

```bash
cd /path/to/HackKU-2026
make deps
make env
make run
```

What those do:

- `make deps` creates `.venv/` if needed and installs Python packages from `frontend/requirements.txt`
- `make env` copies `.env.example` to `.env` if `.env` does not exist yet
- `make run` starts the PySide6 desktop frontend

## Daily use

```bash
cd /path/to/HackKU-2026
make run
```

## Optional checks

```bash
make typecheck
make test
make check
```

## Manual commands

If you do not want to use `make`:

```bash
cd /path/to/HackKU-2026
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r frontend/requirements.txt
cp .env.example .env
python frontend/app/main.py
```
