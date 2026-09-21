# Precision Touchpad input

## Official API findings

The implementation was checked against Microsoft's Windows 11 Precision Touchpad documentation on
2026-09-21:

- `RegisterTouchpadCapableWindow(HWND, BOOL)` opts a specific window into touchpad pointer input.
  It is exported by User32 ordinal 2689 and requires Windows 11.
- `GetPointerFrameTouchpadInfo(UINT32, UINT32*, POINTER_TOUCH_INFO*)` retrieves active contacts in a
  touchpad frame. It is exported by User32 ordinal 2693.
- Touchpad-relative positions are `ptHimetricLocationRaw`. `GetPointerDeviceRects` supplies the
  device rectangle required for normalization.

Official references:

- <https://learn.microsoft.com/windows/win32/input-precisiontouchpad/registertouchpadcapable>
- <https://learn.microsoft.com/windows/win32/input-precisiontouchpad/getpointertouchpadinfo>
- <https://learn.microsoft.com/windows/win32/input-precisiontouchpad/precision-touchpad-portal>

## Important platform constraint

The public API does **not** turn a Precision Touchpad into a general raw multitouch digitizer.
Microsoft documents that:

- one-finger mousing is discarded and converted to mouse input;
- opted-in windows receive touchpad `WM_POINTER` messages for two-finger manipulation gestures;
- disambiguation can discard early frames and later synthesize a down frame;
- taps and holds can be resolved before pointer manipulation delivery.

Consequently, the current Windows API cannot be truthfully claimed to provide every one-finger raw
contact or every two-finger tap to a normal desktop application. Direct HID access is not used: the
touchpad collection is owned by the system input stack, and bypassing it would require unsafe or
unsupported driver-level behavior prohibited by this project.

## Implemented provider

`PrecisionTouchpadInputProvider`:

1. Resolves the two Windows 11 functions from their documented User32 ordinals.
2. Registers only the native ink-canvas window while Writing Mode is active.
3. Reads `WM_POINTERDOWN/UPDATE/UP` frames.
4. Decodes `POINTER_TOUCH_INFO` with the official ABI.
5. Normalizes himetric device coordinates to `[0, 1]`.
6. Feeds platform-neutral `ContactEvent` values to `GestureEngine`.
7. Unregisters the window when Writing Mode stops or the application closes.

It does not install a driver, hook global input, disable the touchpad, or request administrator
rights.

## Practical interaction

- One-finger writing uses the window-local pointer stream that Windows produces for the touchpad.
  This retains timestamps and both raw window and normalized coordinates, but it is not independent
  per-contact HID data.
- Native two-finger frames are inspected when Windows exposes them.
- A two-finger tap normally becomes right-click when that gesture is enabled in Windows Settings;
  right-click inside the canvas commits the current word and inserts a space.
- Spacebar and the commit button remain explicit fallbacks.

## Hardware validation required

Window registration and unregistration were successfully exercised against a real Qt canvas HWND
on the assessed machine. On the target laptop, continue validating:

1. Two-finger scroll frames contain correct IDs and himetric coordinates.
2. The user's Windows two-finger-tap setting produces right-click in the canvas.
3. One-finger writing does not trigger unintended scroll or navigation.
4. No input behavior changes outside the TouchWrite window or after Writing Mode stops.

Automated tests validate API export presence, structure layout invariants, and synthetic gesture
classification. They cannot validate OEM firmware or Windows gesture settings.
