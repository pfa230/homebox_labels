# Homebox Label Generator

Generate Avery 5163-compliant PDF label sheets for Homebox locations and assets,
including QR codes. The primary entry point is the web UI in
`homebox_labels_web.py`, which orchestrates API retrieval, layout, and PDF
rendering.

## Requirements

- Python 3.11+
- A Homebox instance + API credentials

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a `.env` file (or export these env vars):
```
HOMEBOX_API_URL=http://localhost:7745
HOMEBOX_USERNAME=...
HOMEBOX_PASSWORD=...
```

## Web UI

```bash
USE_RELOADER=1 python homebox_labels_web.py
```

## Templates

Templates live under `label_templates/` and control page geometry, typography,
and optional output types. Each template exposes its supported options through
`available_options()` and may define its own page size (PDF) or output behavior
(PNG bundle for non‑page templates).

## Troubleshooting

- **Authentication failures**: confirm `HOMEBOX_API_URL`, `HOMEBOX_USERNAME`,
  and `HOMEBOX_PASSWORD`. The API login request must succeed.
- **Layout drift**: adjust offsets/padding in the template modules and print a
  calibration sheet.
- **Font issues**: templates download fonts into `fonts/` on demand; pre‑seed
  the directory if running offline.

## Development

```bash
python -m pip install -r requirements-dev.txt
pyright
flake8
python -m unittest discover -s tests -p "test_*.py" -v
```

## License

MIT. See `LICENSE`.
