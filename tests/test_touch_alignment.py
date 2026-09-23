from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF

from touchwrite.ui.touch_alignment import TouchAlignmentCanvas


def test_alignment_records_target_and_mapping_error(tmp_path, qtbot) -> None:
    canvas = TouchAlignmentCanvas(tmp_path / "alignment.json")
    qtbot.addWidget(canvas)
    canvas.resize(640, 400)
    canvas.show()
    qtbot.waitExposed(canvas)
    origin = canvas.mapToGlobal(QPoint(0, 0))
    for target in canvas.targets():
        global_position = QPointF(origin.x() + target.x(), origin.y() + target.y())
        canvas.record_touch(target, global_position)
        qtbot.wait(1)

    qtbot.waitUntil(lambda: canvas.results[-1].paint_timestamp_ns is not None)
    assert len(canvas.results) == 9
    assert all(result.target_error_px == 0 for result in canvas.results)
    assert all(result.mapping_error_px == 0 for result in canvas.results)
    assert canvas.metrics()["max_mapping_error_px"] == 0
    assert canvas.metrics()["median_pointer_to_ink_latency_ms"] is not None
    assert (tmp_path / "alignment.json").is_file()
