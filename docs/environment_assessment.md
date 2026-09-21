# Environment assessment

Assessment date: 2026-09-21

## Detected environment

- Operating system: 64-bit Windows 11, build 26200. `Get-ComputerInfo` reports the legacy
  product label "Windows 10 Pro" while Python reports Windows 11; the build is authoritative.
- Default Python: CPython 3.13.7, 64-bit. TouchWrite targets 3.11–3.13; 3.12 remains the preferred
  deployment version because ML package support tends to stabilize there first.
- Git: installed.
- Compiler/native tools: Visual Studio Build Tools, MSVC `cl`, CMake, Ninja, and discoverable
  Windows SDK headers were not found.
- Python packages already present: NumPy, OpenCV, Pillow, PyTorch, Transformers, pytest, and ruff.
  PySide6 was not present at assessment time.
- Hardware enumeration exposes `HID-compliant touch pad` (`HID\VEN_06CB...`) plus its
  HID-compliant mouse collection. This supports the likelihood of a Precision Touchpad, but PnP
  enumeration alone does not prove that application-level contact data is available.

## Capture strategy

The always-available development path is a window-local mouse provider. The native path uses
official Win32 pointer messages only inside the TouchWrite window and is kept behind an input
provider interface. It will never install or replace a driver, globally hook input, or disable the
touchpad.

The proposed `RegisterTouchpadCapableWindow` / `GetPointerTouchpadInfo` symbols could not be
verified in an installed SDK because no SDK headers are present. Native implementation must be
checked against a locally installed Windows SDK before it is declared operational. A small C++
bridge is preferred if Qt's native event boundary cannot reliably expose the required contact
information.

## Limitations and validation status

- **Implemented:** environment detection, mouse-based live ink foundation.
- **Hardware validation required:** independent one-finger touchpad contact coordinates,
  suppression of scroll gestures while writing mode is active, and two-finger tap delivery.
- Native compilation is blocked on this machine until Visual Studio 2022 Build Tools with the
  Desktop development with C++ workload and a Windows 11 SDK are installed.
- No drivers were changed and no administrator-only capture mechanism was introduced.

## Chosen implementation strategy

Build and verify the complete Python domain, rendering, recognition, persistence, gesture, and UI
pipeline with simulated pointer events and mouse input. Keep native input as an isolated provider,
then compile and hardware-test its bridge after an official SDK is installed. Mouse fallback must
remain functional regardless of native-provider availability.
