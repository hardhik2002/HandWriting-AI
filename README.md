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
- Recognition diagnostics that save the exact image tensor seen by TrOCR.

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

Processor behavior is intentionally fixed to the checkpoint-compatible slow processor. Generation
uses deterministic beam search; random sampling is disabled. The recognition raster uses a measured
6 px stroke width; the controlled historical/touchscreen comparison is in
[`reports/live_accuracy_recovery.md`](reports/live_accuracy_recovery.md).

## Run

```powershell
python -m touchwrite.app.main
```

TouchWrite opens as a large, scrollable document whiteboard. It auto-detects a Qt touchscreen when
available and also offers explicit Touch Screen, Precision Touchpad, and Mouse modes. A temporary
prediction appears after the configurable 500 ms idle debounce;
only Space/two-finger tap or Enter commits text. Recognition runs on one background worker, so the
next word can be written while an earlier commit is still resolving.

## Controls

| Input | Action |
|---|---|
| Direct touchscreen contact / left mouse drag | Write a stroke directly under the pointer |
| Two-finger tap where Windows maps it to right-click | Commit word and insert one space |
| Right-click in canvas | Explicit fallback for commit + space |
| Spacebar in mouse mode | Commit word and insert one space |
| Enter | Commit the current word (if any), create a new line, and keep it visible |
| Backspace | Remove last active stroke, otherwise delete text |
| Escape | Clear current uncommitted ink |
| Ctrl+Z / Ctrl+Y | Undo / redo strokes and logical document actions |

Keyboard handling is scoped to the TouchWrite window. Use **Edit Text** for a multiline plain-text
editor backed by the same structured document state.

## Configuration

Settings use `TOUCHWRITE_` environment variables. Common examples:

```powershell
$env:TOUCHWRITE_MODEL_DEVICE = "cpu"
$env:TOUCHWRITE_SMOOTHING_ENABLED = "true"
$env:TOUCHWRITE_SAVE_SAMPLES = "true"
$env:TOUCHWRITE_INPUT_MODE = "touchscreen"
$env:TOUCHWRITE_AUTO_DETECT_INPUT = "true"
$env:TOUCHWRITE_PREVIEW_DEBOUNCE_MS = "500"
$env:TOUCHWRITE_AUTOSAVE_ENABLED = "true"
$env:TOUCHWRITE_DEBUG_INPUT = "false"
$env:TOUCHWRITE_DEBUG_RECOGNITION = "false"
python -m touchwrite.app.main
```

See `touchwrite/config/settings.py` for all typed defaults.

The latest document is atomically autosaved to `data/documents/latest.json` and restored on the
next launch. Use **Export** for a plain-text copy. Streaming and accuracy measurements are shown
under **Diagnostics**; the golden-sample result is documented in
[`reports/whiteboard_regression.md`](reports/whiteboard_regression.md).

**Diagnostics** opens the nine-target Touch Alignment Test. Enable
`TOUCHWRITE_DEBUG_INPUT=true` to save touch coordinate/event logs plus capture, display,
recognition, raw, processed, and model-input artifacts under `data/debug/touchscreen/`. Recognition
lifecycle transitions are written to `recognition_timeline.jsonl`; individual pointer moves are not
logged.

## Tests and lint

No physical touchpad or model download is required for automated tests:

```powershell
pytest
ruff check .
python -m compileall -q touchwrite
```

Run recognition directly against an image without the GUI:

```powershell
python -m touchwrite.tools.test_recognition data\handwriting\<sample-id>\processed.png
```

Replay one saved raw trajectory through the historical finalized-word, V2 commit, and V2 preview
paths, or run the separately labeled touchscreen suite:

```powershell
python -m touchwrite.tools.replay_sample data\handwriting\<sample-id> --expected <label>
python -m touchwrite.tools.regress_touchscreen
python -m touchwrite.tools.regress_whiteboard
```

Replay artifacts and pixel-level comparisons are written under `reports/replay/` or
`reports/touchscreen_replay/`; source sample directories are read-only.

Run the bounded preprocessing and recognizer benchmarks, or regenerate the trajectory comparison:

```powershell
python -m touchwrite.tools.benchmark_preprocessing
python -m touchwrite.tools.benchmark_recognizers --include-large
python -m touchwrite.tools.compare_trajectories
```

Enable `TOUCHWRITE_DEBUG_RECOGNITION=true` to save `raw_strokes.png`, `rendered.png`,
`processed.png`, and the exact human-viewable `model_input.png` under
`data/debug/recognition/<word-id>/`.

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

For structured personalization data, initialize a guided session, commit handwriting in TouchWrite,
then attach each immutable sample ID to its known label. The queue covers uppercase, lowercase,
digits, short words, common English, and project-specific technical terms. Each record retains the
session ID, label, model outputs, raw trajectory, raw image, and processed-image paths.

```powershell
python -m touchwrite.tools.collect_dataset init --participant local-user --repeats 3
python -m touchwrite.tools.collect_dataset add data\collection\<session-id> <sample-id> "hi"
python -m touchwrite.tools.collect_dataset status data\collection\<session-id>
```

For the measured touchscreen accuracy benchmark, use the dedicated full-screen collector. It shows
one authoritative target at a time and saves the raw trajectory, current render, tight crop, exact
384×384 model input, tensor statistics, beam candidates, and preprocessing configuration. It uses
the current recognizer unchanged and continuously refreshes `reports/touchscreen_baseline.md` and
`reports/touchscreen_baseline.json`.

```powershell
python -m touchwrite.tools.collect_accuracy
```

The default queue contains 115 samples, including ten repetitions each of `hi`, `is`, `it`, `in`,
`I`, `am`, and `hardhik`. If collection is interrupted, resume the session without relabeling or
repeating completed prompts:

```powershell
python -m touchwrite.tools.collect_accuracy --resume data\accuracy\<session-id>
```

After collection, run the bounded preprocessing grid against those exact trajectories while keeping
the historical golden set as a hard comparison:

```powershell
python -m touchwrite.tools.benchmark_preprocessing `
  --accuracy-session data\accuracy\<session-id>
```

The generated `index.html` inside the session places raw, processed, cropped, and exact model-input
images side by side for human legibility review. Handwriting session data remains local and ignored
by Git.

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
- [`reports/recognition_diagnosis.md`](reports/recognition_diagnosis.md)
