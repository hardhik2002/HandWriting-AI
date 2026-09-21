# TouchWrite

TouchWrite is a local Windows desktop application for word-at-a-time handwriting. Draw a word in
the ink area, commit it, and a local handwriting model inserts editable text while retaining the
original online trajectory and rendered images for future personalization.

> Screenshot placeholder: run the application and capture the main ink canvas, prediction row,
> and editable text area.

## Current status

- Live, antialiased mouse/finger-as-pointer ink with raw coordinates, normalized coordinates, and
  monotonic timestamps.
- Asynchronous local recognition with `microsoft/trocr-base-handwritten`; the model is loaded once.
- Word commits, spaces, newlines, stroke undo, committed-word undo, backspace, and clear.
- Append-only trajectory/image samples and a correction dialog for labels.
- Native Windows 11 Precision Touchpad API registration and frame decoding where Windows exposes
  manipulation frames.
- Mouse fallback is always retained because Windows normally converts one-finger touchpad motion to
  mouse input before desktop applications see it.
- Evaluation and dataset-export commands with measured CER, WER, word accuracy, and latency.

The native touchpad path is implemented but still requires interactive hardware validation. See
[`docs/touchpad_input.md`](docs/touchpad_input.md) for the exact Windows API limitation.

## Architecture

```text
PySide6 UI / window-local input
        │
        ├── online StrokeBuffer ── smoothing ── aspect-preserving renderer
        │                                      │
        │                                      └── TrOCR worker (CPU/CUDA)
        │                                                   │
        └── editable text / undo state ◄────────────────────┘
                                    │
                                    └── append-only local dataset
```

Details: [`docs/architecture.md`](docs/architecture.md).

## Supported system

- Windows 11 x64
- Python 3.12 recommended; Python 3.11 and 3.13 are supported by the project metadata
- CPU inference works; CUDA is selected automatically when PyTorch reports it available

The new touchpad pointer APIs require Windows 11. Mouse mode remains usable when those exports are
unavailable.

## Install (PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,ml]"
```

## Model setup

The default model is downloaded from Hugging Face on the first recognition and cached in the user
profile. To pre-cache it, run:

```powershell
python -c "from transformers import TrOCRProcessor, VisionEncoderDecoderModel; n='microsoft/trocr-base-handwritten'; TrOCRProcessor.from_pretrained(n); VisionEncoderDecoderModel.from_pretrained(n)"
```

After it is cached, recognition performs no required network call. Configure another compatible
model with `TOUCHWRITE_MODEL_NAME`; no recognizer code changes are needed.

## Run

```powershell
python -m touchwrite.app.main
```

On first run, draw in the white canvas using left mouse drag. Press **Space** or select
**Recognize + Space** to recognize the current word. Press **Start Writing Mode** to opt the window
into native Windows 11 touchpad pointer messages.

## Controls

| Input | Action |
|---|---|
| Left mouse drag / one-finger pointer motion | Write a stroke |
| Two-finger tap where Windows maps it to right-click | Commit word and insert one space |
| Right-click in canvas | Explicit fallback for commit + space |
| Spacebar in mouse mode | Commit word and insert one space |
| Enter | Commit word and insert newline |
| Backspace | Remove last active stroke, otherwise delete text |
| Escape | Clear current uncommitted ink |
| Ctrl+Z | Undo a stroke/clear or restore the last committed word to the canvas |

Keyboard handling is scoped to the TouchWrite window. When the editable text area has focus, it
receives normal editing keys.

## Configuration

Settings use `TOUCHWRITE_` environment variables. Common examples:

```powershell
$env:TOUCHWRITE_INPUT_MODE = "mouse"
$env:TOUCHWRITE_MODEL_DEVICE = "cpu"
$env:TOUCHWRITE_SMOOTHING_ENABLED = "true"
$env:TOUCHWRITE_SAVE_SAMPLES = "true"
$env:TOUCHWRITE_DEBUG_INPUT = "false"
python -m touchwrite.app.main
```

See `touchwrite/config/settings.py` for all typed defaults.

## Tests and lint

No physical touchpad or model download is required for automated tests:

```powershell
pytest
ruff check .
python -m compileall -q touchwrite
```

## Dataset and corrections

Every successful commit creates a new immutable directory under:

```text
data/handwriting/<word-id>/
├── trajectory.json
├── metadata.json
├── raw.png
└── processed.png
```

Use **Correct last prediction** to add the expected label. Raw files are never overwritten. Export
labeled samples with:

```powershell
python -m touchwrite.tools.export_dataset
```

## Evaluation

After correcting a meaningful number of samples:

```powershell
python -m touchwrite.tools.evaluate
```

Reports are written under `reports/` and include exact word accuracy, character error rate, word
error rate, per-sample output, and measured average inference latency. No unmeasured accuracy claim
is made.

## Privacy

Handwriting stays on the local machine. TouchWrite installs no driver, captures no global keyboard
input, requires no administrator rights, and uploads no handwriting data. Model download is the only
normal reason for network access.

## Troubleshooting

- **First recognition is slow:** weights are downloading and loading; later words reuse the model.
- **CUDA requested but unavailable:** TouchWrite logs a warning and falls back to CPU.
- **Recognition failed:** the ink remains on canvas; review the status bar/log output.
- **Start Writing Mode fails:** update Windows 11. Mouse mode remains available.
- **Two-finger tap does not commit:** ensure Windows touchpad settings map two-finger tap to
  right-click, or use right-click/Space. Raw tap contacts are not guaranteed by the public API.
- **Hugging Face symlink warning:** Windows caching still works; Developer Mode reduces duplicate
  cache storage but is not required.

## Documentation

- [`docs/environment_assessment.md`](docs/environment_assessment.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/touchpad_input.md`](docs/touchpad_input.md)
- [`docs/recognition_pipeline.md`](docs/recognition_pipeline.md)
- [`docs/personalization.md`](docs/personalization.md)
