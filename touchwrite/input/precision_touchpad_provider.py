"""Window-scoped Windows Precision Touchpad pointer integration.

Windows currently exposes raw contact frames to ordinary desktop apps only after it classifies a
two-finger interaction as a manipulation gesture. One-finger mousing and taps can remain converted
to mouse messages by the OS. This provider therefore supplements, rather than replaces, the
window-local mouse capture path.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

from touchwrite.input.base import ContactEvent, ContactPhase, GestureAction
from touchwrite.input.gesture_engine import GestureEngine

LOGGER = logging.getLogger(__name__)

WM_POINTERUPDATE = 0x0245
WM_POINTERDOWN = 0x0246
WM_POINTERUP = 0x0247
POINTER_FLAG_DOWN = 0x00010000
POINTER_FLAG_UPDATE = 0x00020000
POINTER_FLAG_UP = 0x00040000


class POINTER_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerType", wintypes.DWORD),
        ("pointerId", wintypes.DWORD),
        ("frameId", wintypes.DWORD),
        ("pointerFlags", wintypes.DWORD),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", wintypes.POINT),
        ("ptHimetricLocation", wintypes.POINT),
        ("ptPixelLocationRaw", wintypes.POINT),
        ("ptHimetricLocationRaw", wintypes.POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", wintypes.DWORD),
        ("inputData", wintypes.INT),
        ("dwKeyStates", wintypes.DWORD),
        ("performanceCount", ctypes.c_uint64),
        ("buttonChangeType", wintypes.DWORD),
    ]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("touchFlags", wintypes.DWORD),
        ("touchMask", wintypes.DWORD),
        ("rcContact", wintypes.RECT),
        ("rcContactRaw", wintypes.RECT),
        ("orientation", wintypes.DWORD),
        ("pressure", wintypes.DWORD),
    ]


class TouchpadApi:
    REGISTER_ORDINAL = 2689
    FRAME_INFO_ORDINAL = 2693

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Precision Touchpad API is available only on Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_proc_address = kernel32.GetProcAddress
        get_proc_address.argtypes = [wintypes.HMODULE, ctypes.c_void_p]
        get_proc_address.restype = ctypes.c_void_p

        register_address = get_proc_address(
            self._user32._handle, ctypes.c_void_p(self.REGISTER_ORDINAL)
        )
        frame_address = get_proc_address(
            self._user32._handle, ctypes.c_void_p(self.FRAME_INFO_ORDINAL)
        )
        if not register_address or not frame_address:
            raise OSError("this Windows build does not export the touchpad pointer APIs")
        register_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.BOOL)
        frame_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(POINTER_TOUCH_INFO),
        )
        self._register = register_type(register_address)
        self._get_frame = frame_type(frame_address)
        self._get_rects = self._user32.GetPointerDeviceRects
        self._get_rects.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.RECT),
            ctypes.POINTER(wintypes.RECT),
        ]
        self._get_rects.restype = wintypes.BOOL

    @classmethod
    def is_available(cls) -> bool:
        try:
            cls()
        except OSError:
            return False
        return True

    def register_window(self, hwnd: int, enable: bool) -> None:
        if not self._register(wintypes.HWND(hwnd), wintypes.BOOL(enable)):
            error = ctypes.get_last_error()
            raise OSError(error, "RegisterTouchpadCapableWindow failed")

    def frame(self, pointer_id: int) -> list[ContactEvent]:
        count = wintypes.DWORD(0)
        self._get_frame(pointer_id, ctypes.byref(count), None)
        if count.value == 0:
            return []
        buffer = (POINTER_TOUCH_INFO * count.value)()
        capacity = wintypes.DWORD(count.value)
        if not self._get_frame(pointer_id, ctypes.byref(capacity), buffer):
            error = ctypes.get_last_error()
            raise OSError(error, "GetPointerFrameTouchpadInfo failed")
        timestamp = time.monotonic_ns()
        return [self._to_event(buffer[index], timestamp) for index in range(capacity.value)]

    def _to_event(self, value: POINTER_TOUCH_INFO, timestamp_ns: int) -> ContactEvent:
        info = value.pointerInfo
        flags = info.pointerFlags
        if flags & POINTER_FLAG_DOWN:
            phase = ContactPhase.DOWN
        elif flags & POINTER_FLAG_UP:
            phase = ContactPhase.UP
        else:
            phase = ContactPhase.MOVE
        device_rect = wintypes.RECT()
        screen_rect = wintypes.RECT()
        if not self._get_rects(
            info.sourceDevice, ctypes.byref(device_rect), ctypes.byref(screen_rect)
        ):
            error = ctypes.get_last_error()
            raise OSError(error, "GetPointerDeviceRects failed")
        width = max(1, device_rect.right - device_rect.left)
        height = max(1, device_rect.bottom - device_rect.top)
        location = info.ptHimetricLocationRaw
        x = min(1.0, max(0.0, (location.x - device_rect.left) / width))
        y = min(1.0, max(0.0, (location.y - device_rect.top) / height))
        return ContactEvent(phase, int(info.pointerId), x, y, timestamp_ns)


class PrecisionTouchpadInputProvider(QAbstractNativeEventFilter):
    def __init__(
        self,
        gesture_engine: GestureEngine,
        on_action: Callable[[GestureAction], None],
    ) -> None:
        super().__init__()
        self.api = TouchpadApi()
        self.gesture_engine = gesture_engine
        self.on_action = on_action
        self.hwnd: int | None = None

    def start(self, hwnd: int) -> None:
        self.api.register_window(hwnd, True)
        self.hwnd = hwnd
        LOGGER.info("Precision Touchpad pointer input enabled for hwnd=%s", hwnd)

    def stop(self) -> None:
        if self.hwnd is not None:
            self.api.register_window(self.hwnd, False)
            LOGGER.info("Precision Touchpad pointer input disabled")
        self.hwnd = None
        self.gesture_engine.reset()

    def nativeEventFilter(self, event_type: bytes, message: int) -> tuple[bool, int]:  # noqa: N802, ARG002
        native_message = wintypes.MSG.from_address(int(message))
        if self.hwnd is None or native_message.hWnd != self.hwnd:
            return False, 0
        if native_message.message not in {WM_POINTERDOWN, WM_POINTERUPDATE, WM_POINTERUP}:
            return False, 0
        pointer_id = int(native_message.wParam) & 0xFFFF
        try:
            for contact in self.api.frame(pointer_id):
                for action in self.gesture_engine.process(contact):
                    self.on_action(action)
        except OSError as error:
            LOGGER.warning("touchpad frame rejected: %s", error)
        return False, 0
