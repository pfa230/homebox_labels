# Homebox Label Generator

Generate Avery 5163-compliant PDFs for Homebox locations and assets with QR codes.

## Requirements

- Python 3.11+
- A Homebox instance + API credentials

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a `.env` file:
```
HOMEBOX_API_URL=http://localhost:7745
HOMEBOX_USERNAME=...
HOMEBOX_PASSWORD=...
```

## CLI

```bash
python homebox_labels.py
```

## Web UI

```bash
USE_RELOADER=1 python homebox_labels_web.py
```

## Development

```bash
python -m pip install -r requirements-dev.txt
pyright
flake8
python -m unittest discover -s tests -p "test_*.py" -v
```

## License

MIT. See `LICENSE`.
