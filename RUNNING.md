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

## Linux emoji support

If reaction or avatar emojis show up as boxes on Linux, install a color emoji font:

```bash
sudo apt install fonts-noto-color-emoji
```

## Manual commands

```bash
cd /path/to/HackKU-2026
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r src/fronatend/requirements.txt
cp .env.example .env
PYTHONPATH=src/fronatend python src/fronatend/app/main.py
```
