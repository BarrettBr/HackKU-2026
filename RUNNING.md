# Running The Frontend

## First-time setup

```bash
cd /path/to/HackKU-2026
make deps
make env
make run
```

## Daily use

```bash
cd /path/to/HackKU-2026
make run
```

## Manual commands

```bash
cd /path/to/HackKU-2026
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r frontend/requirements.txt
cp .env.example .env
PYTHONPATH=frontend python frontend/app/main.py
```
