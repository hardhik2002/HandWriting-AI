# TouchWrite V2 touchscreen diagnosis

Date: 2026-09-23

## Reproduction environment

- Windows reports both `HID-compliant touch screen` and `HID-compliant touch pad` devices.
- Qt reports one pointing device of type `TouchScreen`, with `Position`, `Area`,
  `NormalizedPosition`, and `MouseEmulation` capabilities and ten maximum points.
- Primary touchscreen display: 1280×720 logical pixels, 1280×672 available, DPR 1.5,
  effective Windows DPI 144 (150%).
- Secondary display: 1366×768 logical pixels, DPR 1.0.
- The live V2 window was reproduced and captured at 1195×737 while its requested initial size was
  1180×820, larger than the primary screen's available logical height.

## Current event path

```text
Windows touchscreen
  -> Qt TouchScreen device with MouseEmulation
  -> synthesized QMouseEvent (the widget does not accept touch events)
  -> InkCanvas.mousePress/Move/ReleaseEvent
  -> MouseInputProvider.point(event.position())
  -> Point.x_raw/y_raw in canvas-local logical pixels
  -> StrokeBuffer
```

`InkCanvas` does not enable `WA_AcceptTouchEvents` and has no `QTouchEvent` handler. Therefore V2
cannot retain touch contact identity, pressure, native touch phases, or distinguish direct touch
from an ordinary mouse before this fix.

## UI root cause

The toolbar adds text-only `QAction` objects without icons but never sets
`ToolButtonTextOnly`/`ToolButtonTextBesideIcon`. The platform toolbar default is icon-oriented, so
the actions occupy space while their labels are not painted. A single toolbar also attempts to fit
all commands on one row. At 1280 logical pixels and 150% display scaling, the result is blank and
overflowed controls.

## Coordinate root cause

Capture uses canvas-local logical coordinates correctly, but `paintEvent` does not paint those
coordinates. It applies:

```text
translate_x = text_cursor_x - first_point.x_raw
translate_y = text_cursor_y - 38 - first_point.y_raw
paint = raw + translation
```

This intentionally moves live handwriting away from the finger and toward the logical text cursor.
It is the direct cause of the large top/left displacement.

It also corrupts newly captured multi-stroke words indirectly: after stroke one is displayed at a
translated location, the user places stroke two next to that visible stroke. Stroke two is then
captured at the translated screen location while stroke one's recognition geometry remains at its
original raw location. The combined recognition trajectory contains an artificial gap/scale and
can produce a poor processed image even though the renderer itself remains correct.

## DPI and scrolling findings

Qt reports event positions and widget geometry in logical pixels. No manual DPR conversion exists
in the current mouse path, and none should be added. DPR 1.5 contributes to the cramped physical
UI but is not the source of the cursor translation.

The canvas is the scroll area's content widget. A local event delivered to the canvas already uses
document/canvas coordinates, including the current scroll position. The current code does not
explicitly mix scrollbar values into recognition. Named mapping functions and diagnostics are
still required to prevent future viewport/global/canvas confusion.

## Duplicate-event finding before the fix

Only the mouse handler records strokes because touch events are not accepted. Thus the old code
does not record both a `QTouchEvent` and its synthesized mouse counterpart; it records only the
synthesized mouse path. When native Qt touch handling is enabled, synthesized mouse events must be
explicitly rejected to preserve one physical stroke per contact.

## Recognition boundary

The renderer consumes only `Point.x_raw/y_raw`, preserves physical aspect ratio, and remains the
known-good component. The fix must preserve local capture geometry for recognition and change only
input/event/display handling.
