# Native integration

TouchWrite currently uses a minimal Python `ctypes` bridge for the documented Windows 11 User32
touchpad APIs. This avoids a native build dependency while preserving the exact Win32 structures and
calling convention.

A C++ bridge is not currently required. If SDK evolution or Qt native-event behavior makes one
necessary, install Visual Studio 2022 Build Tools with **Desktop development with C++** and a current
Windows 11 SDK, then keep the bridge boundary limited to normalized contact events. Do not add a
kernel driver or direct HID filter.

