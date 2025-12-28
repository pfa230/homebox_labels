# Homebox Labels

Generate sheet or individual labels for Homebox locations and assets using
pluggable templates. This project ships with:

- **Avery 5163** 2"x4" sheets (customizable per-label orientation)
- **Brother P‑touch 24mm** continuous tape (normal + minimal)

The primary entry point is the web UI in `homebox_labels_web.py`.

## Motivation

Homebox’s built‑in label support is rudimentary. Locations only have UUIDs, which
are useless on physical labels. This project treats a portion of the **location
name** as a human‑readable **ID**, prints it consistently, and renders QR codes to
jump directly to the Homebox UI.

## Location IDs (Name Parsing)

Because Homebox doesn’t support user‑friendly IDs, we encode them in the name.

Default convention:

```
BOX.010 | Electrical Supplies
RACK.005 | Left rack on front wall
```

- The ID format is `<TYPE>.<NUMBER>` (e.g., `BOX.010`, `RACK.005`).
- Fixed width numeric IDs keep font size consistent and readable.
- The default separator is `|`, but the matching regex is configurable.

You can override the pattern with:

```
HOMEBOX_LOCATION_ID_REGEX=...
```

## Workflow (How I Use It)

Because Homebox doesn’t auto‑increment IDs:

1. Add locations as `BOX.XXX | Some name`.
2. Fill them with items in Homebox.
3. Open `homebox_labels_web` (the “Show only with ID” toggle is **on** by default).
4. The table is sorted by **ID (desc)**, so all `BOX.XXX` entries are grouped up top.
5. Find the largest ID just below the last `BOX.XXX` (e.g., `BOX.072`).
6. Click the `BOX.XXX` link to open the Homebox location.
7. Rename to `BOX.073`, `BOX.074`, etc.
8. Select the new IDs and generate labels.

## Templates

### Avery 5163 (2"x4" sheets)

- Sheet PDF output.
- Per‑label options: orientation (horizontal/vertical) + outline.
- You can print multiple copies of each label in different orientations. Useful for e.g.
  Sterilite boxes that need horizontal labels on side face and vertical on end face.

### Brother P‑touch 24mm

- Individual label output (zipped PNG bundle).
- Options: `normal` or `minimal`.
- For chain printing the zipped PNG bundles on macOS, this is very useful:
  [ptouch-print-macOS](https://github.com/pfa230/ptouch-print-macOS)

Templates use a fork of Inter with slashed zero, available at
[pfa230/inter](https://github.com/pfa230/inter). The font itself is bundled with
the project.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a `.env` file (or export vars):

```
HOMEBOX_API_URL=http://localhost:7745
HOMEBOX_USERNAME=...
HOMEBOX_PASSWORD=...
# Optional
HOMEBOX_LOCATION_ID_REGEX=^\s*([^|]+?)\s*\|\s*(.*)$
```

## Run Locally

```bash
USE_RELOADER=1 python homebox_labels_web.py
```

Default UI is on `http://127.0.0.1:4000` when running locally.

## Run with Docker (Production)

```bash
docker compose up --build
```

The compose file binds the app to `http://localhost:4000`.

## Development

```bash
python -m pip install -r requirements-dev.txt
pyright
flake8
python -m unittest discover -s tests -p "test_*.py" -v
```

## License

MIT. See `LICENSE`.
