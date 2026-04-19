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

## Optional API Keys

Movie lookup uses no-key public lookup first, then the `cinemagoer` Python library as a best-effort fallback after `make deps`. `OMDB_API_KEY` is only an optional richer metadata fallback if your team already has one.

Auto subtitle search uses the OpenSubtitles API instead of scraping subtitle sites. Add `OPENSUBTITLES_API_KEY` to `.env` if you want the host to search for `.srt` files by movie title from inside the app. Hosts can still choose a local `.srt` manually without an API key.

GIF search uses GIPHY when `GIPHY_API_KEY` is set in `.env`. Without a key, the app keeps using the small built-in fallback GIFs.

## Manual commands

```bash
cd /path/to/HackKU-2026
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r src/fronatend/requirements.txt
cp .env.example .env
PYTHONPATH=src/fronatend python src/fronatend/app/main.py
```
