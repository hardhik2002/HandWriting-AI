# TouchWrite V2 whiteboard regression

## Preserved recognition configuration

- Checkpoint: `microsoft/trocr-base-handwritten`
- Processor: slow `TrOCRProcessor` (`use_fast=False`)
- Render: 512×128, 16 px padding, 8 px stroke, 3× supersampling
- Geometry: undistorted raw coordinates with physical aspect ratio preserved
- Preprocessing: three-point moving-average smoothing and isolated-click filtering
- Generation: deterministic, eight beams/eight returned sequences, 24 new tokens, no sampling
- Selection: first clean single-word model beam, with conservative whitespace-only postprocessing

No renderer, smoother, TrOCR processor, generation, beam-selection, checkpoint, or final
postprocessing behavior was changed by the V2 work.

## Golden saved sample

| Sample | Expected | Before prediction | After prediction | Render comparison |
|---|---|---|---|---|
| `ba216970-66de-4d3e-b192-7669dd273b86` | `hardhik` | `hardhik` | `hardhik` | Pixel-identical `(0, 0)` difference extrema |

The before value is the final prediction stored with the sample before the V2 refactor. The after
value was measured by loading the same saved trajectory and running the full current
render/smooth/filter/recognize/postprocess pipeline. Its raw first beam remained `thanchik .`; the
unchanged clean single-word beam selection produced `hardhik`.

## Measured performance

Measurements were taken on CPU on 2026-09-23 using the saved golden sample.

| Path | Measured time |
|---|---:|
| Full post-refactor pipeline inference (warm model after load) | 6,352.4 ms |
| Model load in that process | 6,587.4 ms |
| Separate cold preview wall time (load + render + inference) | 37,714.6 ms |
| Preview model inference within that cold run | 9,522.7 ms |
| Exact-snapshot cached commit (render + finalization, no model call) | 48.4 ms |

The cache reduced the measured exact-snapshot commit path from a multi-second model inference to
48.4 ms. Runtime diagnostics also count preview scheduling delay, preview/commit duration, cache
reuse, stale-preview discards, model loads, and pointer-to-ink latency.

## Automated verification

- `pytest -q`: 45 passed
- `ruff check .`: passed
- `python -m compileall -q touchwrite`: passed
