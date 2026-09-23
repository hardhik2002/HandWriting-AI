# TouchWrite V2 live-recognition A/B investigation

Date: 2026-09-23

## Exact Root Cause

For the three labeled failed touchscreen samples, there is **no V1-versus-V2 recognition input
regression**. Replaying each exact persisted raw trajectory through the finalized-word flow from
Git commit `8c7111f`, the V2 commit path, and the V2 preview path produced pixel-identical 512x128
processed images, pixel-identical 384x384 processor images, and the same prediction.

The observed failures are therefore predictions for the newly captured physical trajectories,
not stale previews, partial snapshots, whiteboard leakage, altered crops, missing dots, or a changed
model pipeline. The current physical `hardhik` trajectory is geometrically different from the
historical golden: raw aspect ratio 5.12 versus 2.96, 9 strokes versus 12, and a different terminal
`ik` construction. This does not claim that aspect ratio alone causes the prediction; it proves the
two samples are not equivalent inputs.

Two genuine sequencing risks were found and hardened, but neither explains the persisted failures:

- Preview cache entries previously did not retain their source revision. Geometry hashes prevented
  the observed `h`/`hi` mistakes, but revision-qualified reuse is now enforced as an additional
  invariant.
- A commit requested while a native contact was still active finalized the buffer immediately.
  Commit now waits for the real touch-end/cancel transition and queues snapshot creation on the Qt
  event loop, with no sleep delay.

## Why Historical Golden Still Worked

The historical sample `ba216970-66de-4d3e-b192-7669dd273b86` still produces `hardhik` through all
three paths. Its persisted processed image is pixel-identical to a fresh replay. It has 12 strokes,
354 points, raw aspect 2.96, processed occupancy 13.93%, and model-input occupancy 15.59%.

The golden proves the shared model pipeline remains functional. It does not make the new physical
trajectory equivalent to the golden trajectory.

## Why Live V2 Samples Failed

Independent UI-free replay reproduced every live failure. The same failures also occur in the
reconstructed V1 finalized-word path. This rules out V2 streaming and document state as the cause
for these saved samples.

The two `hi` samples are complete but sparse short-word inputs. Their processor-image ink occupancy
is 4.06% and 4.58%. That occupancy is not a V2 crop change: V1-style, preview, and commit inputs are
identical for each trajectory. No special zoom, dictionary rule, or decoder correction was added.

A controlled no-smoothing replay did not improve accuracy:

| Sample | Normal smoothing | Smoothing disabled |
|---|---|---|
| `hardhik` physical sample | `hardhijk` | `hardhijk` |
| first `hi` | `32h.i` | `32h.i` |
| second `hi` | `25th I.` | `" H I.` |

The evidence does not support changing smoothing globally.

## `hardhik -> hardhijk` Analysis

Sample `98ae9fd3-cb6c-4533-84f2-6a9fd66f5a8a` contains 9 strokes and 323 points. No stroke is
removed by the isolated-noise filter. The last four strokes are:

| Stroke | Points | Path length | Evidence |
|---:|---:|---:|---|
| 40 | 16 | 43.97 px | `i` stem, retained |
| 41 | 11 | 8.55 px | detached `i` dot, retained |
| 42 | 18 | 53.59 px | first `k` stroke, retained |
| 43 | 26 | 65.80 px | second `k` stroke, retained |

There is no extra terminal click, duplicated dot, filtered dot, duplicated preview stroke, or
partial terminal stroke in the persisted trajectory. V1-style, replay, preview, and commit all
produce `hardhijk`. Five repeated runs are deterministic. The unchanged beams include `hardhi K`,
`nardhi K`, `hardhijk .`, `hardhi k`, `narndhi K`, `hardhijk`, `hardhick`, and `narndhijk`;
exact `hardhik` is absent. The beam therefore genuinely interprets this image with an extra
character; beam selection is not hiding an exact candidate.

## `hi -> 25th I.` Analysis

Sample `0601206f-9beb-49eb-bce3-d855d3923e5d` contains 3 strokes and 85 points. The third stroke,
the `i` dot, contains 14 points, has an 11.26 px path, and is retained. Its raw bounding box is
74.0x45.33 px. The processed foreground is 168x105 px with padding `(172, 12, 172, 11)` and 4.07%
occupancy. The 384x384 processor input has 4.58% occupancy.

All paths produce `25th I.`. Five runs are deterministic. The beams include `25th I.`, `" H I.`,
`" H I -`, `25h.i`, `32h.i`, `22h.i`, `than I am`, and `such it .`; exact `hi` is absent.

The other labeled `hi` sample, `3332b0a3-8944-4d93-b914-a07b52d9a6a1`, contains 3 strokes and
66 points. Its detached dot is a 3-point, 0.94 px stroke and is retained. Processed occupancy is
3.60%; processor occupancy is 4.06%. Every path produces `32h.i`, and exact `hi` is absent from its
unchanged beams.

## Preview vs Commit Findings

For every labeled sample:

- preview and commit trajectory hashes match the independently calculated persisted hash;
- V1, V2 preview, and V2 commit processed images differ by 0 pixels;
- V1, V2 preview, and V2 commit model inputs differ by 0 pixels;
- persisted `processed.png` and freshly rendered commit input differ by 0 pixels;
- predictions and five-run beam lists are deterministic.

Lifecycle tracing now records `stroke_started`, `stroke_ended`, `preview_scheduled`,
`preview_snapshot_created`, `new_stroke_started`, `commit_pressed`, `commit_snapshot_created`,
`preview_finished`, and `commit_finished` with monotonic timestamps. Pointer updates are not logged.

## Cache Findings

The trajectory hash includes every recognition-relevant point field and excludes only display-only
coordinates. Adding an `i` dot or another stroke changes the hash. A preview result is now reusable
only when both the trajectory hash and preview revision match the complete commit snapshot.

Tests prove that results for `h`, `hi` without a dot, and `hi` with a dot cannot cross-reuse; caller
mutation after queueing cannot alter a request; and stale/out-of-order previews cannot overwrite the
current revision.

## Stroke Finalization Findings

The failed persisted samples contain their release endpoints, dots, and terminal strokes. They were
not truncated. Nevertheless, the old active-contact commit path could snapshot before a pending
native release. It now defers only while `InkCanvas.input_active` is true and resumes immediately
after `stroke_ended` on the event loop. Tests verify the final release point is present before the
snapshot. No arbitrary delay is used.

## Short-Word Crop Findings

| Expected / sample | Raw bbox | Processed foreground | Processed padding L/T/R/B | Processed occupancy | Model occupancy |
|---|---:|---:|---:|---:|---:|
| `hi` / `3332b0a3` | 56.67x46.67 | 126x106 | 193/11/193/11 | 3.60% | 4.06% |
| `hi` / `0601206f` | 74.00x45.33 | 168x105 | 172/12/172/11 | 4.07% | 4.58% |
| `hardhik` / `98ae9fd3` | 290.00x56.67 | 489x104 | 12/12/11/12 | 15.43% | 17.42% |
| historical `hardhik` | 463.33x156.67 | 365x106 | 74/11/73/11 | 13.93% | 15.59% |

These measurements are identical between the V1-style and V2 paths. Recognition receives only the
active word's strokes; document text, caret, guidelines, toolbar, preview text, prior words, and next
words are never passed to `InkRenderer`.

## Before / After Predictions

The sequencing/cache hardening intentionally does not rewrite predictions for already complete,
persisted trajectories:

| Expected | Live prediction | Replay prediction | V1-style prediction | Preview prediction | Commit prediction |
|---|---|---|---|---|---|
| `hardhik` | `hardhijk` | `hardhijk` | `hardhijk` | `hardhijk` | `hardhijk` |
| `hi` | `32h.i` | `32h.i` | `32h.i` | `32h.i` | `32h.i` |
| `hi` | `25th I.` | `25th I.` | `25th I.` | `25th I.` | `25th I.` |

## Historical Golden Regression

The historical suite remains separate and passes:

```text
ba216970-66de-4d3e-b192-7669dd273b86: hardhik -> hardhik
```

The final regression completed in 3091.6 ms. The historical processed image remains
pixel-identical.

## New Touchscreen Regression

The separately labeled current-touchscreen suite contains only the three samples whose expected
text was explicitly supplied. It reports 0/3 exact words and aggregate CER 90.91% (10 edit errors
over 11 reference characters). This tiny, intentionally failure-focused set is not a general
accuracy estimate. No verified labels exist yet for the requested `I`, `is`, `a`, `to`, `in`, `it`,
`how`, `where`, `you`, `python`, or `touchwrite` samples, so they are not scored.

## Tests

Automated tests cover preview-plus-extra-stroke, pre-dot preview, revision-qualified cache reuse,
commit during active input, rapid commits, SPACE and ENTER boundaries, detached-dot preservation,
current-word-only snapshots, no previous/next word leakage, defensive snapshot copying,
out-of-order inference, pixel metrics, and historical golden pixel identity.

Commands:

```powershell
python -m touchwrite.tools.replay_sample data\handwriting\<sample-id> --expected <label>
python -m touchwrite.tools.regress_touchscreen
python -m touchwrite.tools.regress_whiteboard
pytest
ruff check .
python -m compileall touchwrite
git diff --check
```

Final results: 68 tests passed, Ruff passed, compilation passed, and `git diff --check` passed.

## Files Changed

- `touchwrite/diagnostics/accuracy.py`: read-only replay, geometry, density, occupancy, pixel, CER,
  beam, and determinism evidence.
- `touchwrite/diagnostics/timeline.py`: low-volume monotonic recognition lifecycle trace.
- `touchwrite/tools/replay_sample.py`: one-sample V1/V2 A/B command.
- `touchwrite/tools/regress_touchscreen.py`: separately labeled live-capture regression suite.
- `touchwrite/services/recognition_stream.py`: defensive snapshots and revision-qualified cache reuse.
- `touchwrite/ui/ink_canvas.py`: explicit active-input state and stroke-end signal.
- `touchwrite/ui/main_window.py`: event-sequenced commit finalization and lifecycle tracing.
- `tests/fixtures/touchscreen_regression.json`: external labels for only the known physical tests.
- Diagnostic, stream, UI, renderer, and service tests.

No model, processor, renderer geometry, smoother behavior, beam width, deterministic generation,
beam selection, or postprocessing setting was changed.
