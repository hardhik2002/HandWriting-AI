# TouchWrite V2 touchscreen regression report

Date: 2026-09-23

## UI Root Cause

The live toolbar contained text-only `QAction` objects but used Qt's icon-oriented default toolbar
style. Because those actions had no icons, their buttons occupied space while their labels were not
painted. All actions were also placed on one row. The initial 1180×820 logical window exceeded the
primary display's 1280×672 available logical height at 150% scaling.

The fixed UI uses two explicit text-only toolbar rows, high-contrast colors, 44+ logical-pixel
targets, large blue Commit/Space and New Line controls, and an explicit narrow-window More menu.
The initial height now derives from the active screen's available logical geometry.

## Touch Coordinate Root Cause

V2 captured synthesized mouse positions in canvas-local logical coordinates, but live painting
applied this translation:

```text
paint_x = raw_x + (text_cursor_x - first_raw_x)
paint_y = raw_y + (text_cursor_y - 38 - first_raw_y)
```

The first live point was therefore always moved to the digital text cursor, not rendered beneath
the finger. Subsequent physical strokes were captured beside the already-translated display ink,
mixing two frames inside one recognition word.

The fix paints `display_x/display_y` directly, while the existing renderer continues consuming only
undistorted `x_raw/y_raw`. Global, viewport, canvas, document, display, and recognition conversions
now have named functions rather than scattered offset arithmetic.

## DPI / Scroll Root Cause

Measured environment:

- Primary touchscreen: 1280×720 logical, 1280×672 available, DPR 1.5, Windows DPI 144.
- Secondary display: 1366×768 logical, DPR 1.0.
- Qt exposes touch positions and widget geometry in logical pixels.

No DPR multiplication or division is required. DPR made the old oversized UI physically cramped,
but did not cause the translation. The canvas is the scroll area's document widget, so a touch
delivered to it is already in scrolled document coordinates. Tests verify viewport-to-canvas and
document-to-view mappings with nonzero scrollbars and after resize.

## Duplicate Event Result

Before the fix the canvas did not accept touch events, so only Qt's synthesized mouse path could
store a stroke. Qt reports the installed device as `TouchScreen` with `MouseEmulation` and ten
contacts.

The fixed canvas accepts `QTouchEvent`, tracks one writing contact ID, accepts the event, and rejects
mouse events whose source is synthesized or whose pointing device is a touchscreen. Secondary
contacts cannot create duplicate strokes. Native-event phase tests cover begin, update, end,
contact identity, and out-of-bounds starts.

## Recognition Regression Root Cause

The TrOCR and renderer pipeline did not regress. The UI's display translation indirectly damaged
new multi-stroke capture: users placed later strokes beside translated ink even though earlier raw
points remained at their original locations. The resulting recognition trajectory had artificial
gaps and aspect changes before reaching the still-correct renderer.

Touchscreen capture, display, and recognition coordinates are now persisted separately in debug
mode under `data/debug/touchscreen/<request-id>/`, together with raw, processed, and model-input
images. Geometry JSON includes capture, display, recognition, and rendered-ink aspect ratios.

## Before vs After Alignment

For the specified example touch `(650, 420)` on an empty line, the old formula painted the first
point at `(56, 44)`: a deterministic displacement of **703.0 logical pixels**. The fixed identity
display mapping paints it at `(650, 420)`.

The automated nine-target alignment test reports 0 px mapping error for exact injected logical
positions, including all corners, edges, and center. This validates the conversion code but is not
presented as a physical touchscreen measurement.

Four real touchscreen commits captured after the fix contain 1,832 points at DPR 1.5. Across all
of them, stored display coordinates equal the undistorted recognition coordinates with a measured
maximum difference of **0.0 logical pixels**. Their capture aspect ratios are 6.79, 3.65, 1.40,
and 1.21; no display transform changes those ratios.

The real Touch Alignment Test is available from **Diagnostics** and writes:

```text
data/debug/touchscreen/touch_alignment_latest.json
```

The completed physical nine-target run reported:

| Metric | Physical touchscreen result |
|---|---:|
| Event type | `QTouchEvent` / `TouchScreen` |
| Device pixel ratio | 1.5 |
| Median global-to-canvas mapping error | 0.33 logical px |
| Maximum global-to-canvas mapping error | 0.33 logical px |
| Median target-touch error (includes finger placement) | 12.41 logical px |
| Maximum target-touch error | 17.75 logical px |
| Median pointer-to-ink latency | 2.91 ms |
| p95 pointer-to-ink latency | 3.56 ms |

Exactly nine records were produced for nine physical taps. No duplicate synthesized-mouse records
appeared. Results cover top-left, top-center, top-right, middle row, bottom-left, bottom-center, and
bottom-right.

## Golden Recognition

| Sample | Expected | Before known-good | Before fix run | After fix run |
|---|---|---|---|---|
| `ba216970-66de-4d3e-b192-7669dd273b86` | `hardhik` | `hardhik` | `hardhik` | `hardhik` |

- Before-fix inference: 3237.7 ms.
- Final after-fix regression inference: 3849.8 ms (CPU latency varies by system load).
- The stored golden processed image remains pixel-identical after regeneration.

New physical touchscreen sample:

| Sample | Intended | Prediction | Raw first beam | Strokes / points | Capture aspect | Coordinate error |
|---|---|---|---|---:|---:|---:|
| `98ae9fd3-cb6c-4533-84f2-6a9fd66f5a8a` | `hardhik` | `hardhijk` | `hardhi K` | 9 / 323 | 5.12 | 0.0 px |

None of the eight unchanged beams was exact `hardhik`. The raw and processed images preserve the
physical handwriting without displacement or scale changes, so the remaining extra-character
error is not attributed to touchscreen coordinates. Per the task constraint, no checkpoint, beam,
processor, selection, or postprocessing change was made to hide it.

A new three-stroke physical touchscreen sample is visually legible as `hi` in its raw and processed
images, but it has no human correction label. TrOCR produced `32h.i`; none of its eight unchanged
beams produced exact `hi`. Since its display and recognition trajectories are identical with 0 px
coordinate difference, this residual result is not caused by the former UI translation. No model,
beam, processor, or postprocessor change was made in response.

## UI Changes

- Explicit Touch Screen, Precision Touchpad, and Mouse modes.
- Automatic touchscreen selection when a Qt touchscreen is present; manual override remains.
- Direct absolute touchscreen drawing with a separate configurable visual stroke width.
- Touch-friendly Commit/Space and New Line buttons.
- Two-row, high-contrast toolbar and responsive More overflow.
- Canvas clipping and rejection of strokes that begin outside the active page.
- Diagnostic crosshairs and a nine-target Touch Alignment Test.

## Tests

Automated coverage includes coordinate mapping, scrolling, resize, native touch phases, contact
identity, multiple contacts, out-of-bounds input, synthesized-mouse suppression, toolbar visibility,
touch target sizing, alignment recording, geometry debug artifacts, hash independence from display
coordinates, and the pixel-identical golden processed image.

Final command results are recorded after the last source change.

- `pytest`: 58 passed.
- `ruff check .`: passed.
- `python -m compileall touchwrite`: passed.
