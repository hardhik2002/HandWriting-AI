from __future__ import annotations

import sys

import pytest

from touchwrite.input.precision_touchpad_provider import (
    POINTER_INFO,
    POINTER_TOUCH_INFO,
    TouchpadApi,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API contract")
def test_touchpad_api_exports_exist_on_supported_build() -> None:
    assert TouchpadApi.is_available()
    assert TouchpadApi().REGISTER_ORDINAL == 2689


def test_pointer_structures_have_expected_nesting() -> None:
    assert POINTER_INFO.performanceCount.offset > POINTER_INFO.dwTime.offset
    assert POINTER_TOUCH_INFO.pointerInfo.offset == 0
    assert POINTER_TOUCH_INFO.pressure.offset > POINTER_TOUCH_INFO.pointerInfo.offset
