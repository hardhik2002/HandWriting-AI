# TouchWrite

TouchWrite is a local Windows desktop application that turns handwriting strokes into editable
text. The current foundation provides a responsive PySide6 ink canvas and mouse fallback; the
recognition, persistence, and native Precision Touchpad layers are added incrementally.

## Quick start (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,ml]"
python -m touchwrite.app.main
```

Run checks with:

```powershell
pytest
ruff check .
```

Handwriting data remains local under `data/handwriting/` and is ignored by Git.

