# Lightweight Asset Tracking System

This repository provides a lightweight Flask-based asset tracking tool that matches your requested scope:

- Track asset ID, part number, description, ownership, location, assignee, calibration date.
- Role-based behavior:
  - **Manager**: add/edit all assets, set status (available/reserved/divested), create users.
  - **User**: view/search/filter all assets and update only **available** assets.
- Barcode + QR support:
  - Generate **Code128 barcode PNG** (300 DPI settings suitable for Brother QL-800 label workflows).
  - Generate **QR code PNG** for each asset.
  - Scan flow via `/scan?code=<asset_id>` to open the record directly.
- Optional user QR login support (`/users/<employee_id>/qrcode.png`) with optional PIN verification.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

Default credentials:
- Manager: `MGR001` / `1234`
- User: `USR001` / `1234`

## Notes

- This is intentionally lightweight and not a procurement/inventory ERP.
- SQLite database file is auto-created at `instance/assets.db`.
