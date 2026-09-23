"""Interactive touchscreen alignment target test."""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QEventPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPointingDevice, QTouchEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from touchwrite.ui.coordinate_mapper import global_to_canvas


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    target: tuple[float, float]
    reported_event_position: tuple[float, float]
    transformed_position: tuple[float, float]
    target_error_px: float
    mapping_error_px: float
    timestamp_ns: int
    device_pixel_ratio: float


class TouchAlignmentCanvas(QWidget):
    changed = Signal()

    def __init__(self, output_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.output_path = output_path
        self.results: list[AlignmentResult] = []
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setMinimumSize(640, 400)
        self.setStyleSheet("background: white; border: 1px solid #cbd5e1;")

    def targets(self) -> list[QPointF]:
        width = max(1.0, self.width() - 120.0)
        height = max(1.0, self.height() - 120.0)
        return [
            QPointF(60.0 + column * width / 2, 60.0 + row * height / 2)
            for row in range(3)
            for column in range(3)
        ]

    def reset(self) -> None:
        self.results.clear()
        self.output_path.unlink(missing_ok=True)
        self.changed.emit()
        self.update()

    def metrics(self) -> dict[str, float | int]:
        if not self.results:
            return {"samples": 0}
        target_errors = [result.target_error_px for result in self.results]
        mapping_errors = [result.mapping_error_px for result in self.results]
        return {
            "samples": len(self.results),
            "median_target_error_px": statistics.median(target_errors),
            "max_target_error_px": max(target_errors),
            "median_mapping_error_px": statistics.median(mapping_errors),
            "max_mapping_error_px": max(mapping_errors),
        }

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.TouchBegin and isinstance(event, QTouchEvent):
            pressed = next(
                (
                    point
                    for point in event.points()
                    if point.state() == QEventPoint.State.Pressed
                ),
                None,
            )
            if pressed is not None:
                self.record_touch(pressed.position(), pressed.globalPosition())
            event.accept()
            return True
        if event.type() in {
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        }:
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        device = event.pointingDevice()
        synthesized = event.source() != Qt.MouseEventSource.MouseEventNotSynthesized
        touchscreen = (
            device is not None and device.type() == QPointingDevice.DeviceType.TouchScreen
        )
        if synthesized or touchscreen:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.record_touch(event.position(), event.globalPosition())
            event.accept()
            return
        super().mousePressEvent(event)

    def record_touch(self, local: QPointF, global_position: QPointF) -> None:
        targets = self.targets()
        if len(self.results) >= len(targets):
            return
        target = targets[len(self.results)]
        transformed = global_to_canvas(self, global_position)
        result = AlignmentResult(
            target=(target.x(), target.y()),
            reported_event_position=(local.x(), local.y()),
            transformed_position=(transformed.x(), transformed.y()),
            target_error_px=math.hypot(
                transformed.x() - target.x(), transformed.y() - target.y()
            ),
            mapping_error_px=math.hypot(
                transformed.x() - local.x(), transformed.y() - local.y()
            ),
            timestamp_ns=time.perf_counter_ns(),
            device_pixel_ratio=self.devicePixelRatioF(),
        )
        self.results.append(result)
        self._save()
        self.changed.emit()
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("white"))
        targets = self.targets()
        for index, target in enumerate(targets):
            if index == len(self.results):
                color, width, radius = QColor("#2563eb"), 3, 16
            elif index < len(self.results):
                color, width, radius = QColor("#94a3b8"), 1, 10
            else:
                color, width, radius = QColor("#cbd5e1"), 1, 10
            painter.setPen(QPen(color, width))
            self._crosshair(painter, target, radius)
        painter.setPen(QPen(QColor("#dc2626"), 2))
        for result in self.results:
            self._crosshair(
                painter,
                QPointF(*result.transformed_position),
                8,
            )

    def _save(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "coordinate_units": "Qt logical pixels",
            "metrics": self.metrics(),
            "results": [asdict(result) for result in self.results],
        }
        self.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _crosshair(painter: QPainter, point: QPointF, radius: float) -> None:
        painter.drawLine(
            QPointF(point.x() - radius, point.y()),
            QPointF(point.x() + radius, point.y()),
        )
        painter.drawLine(
            QPointF(point.x(), point.y() - radius),
            QPointF(point.x(), point.y() + radius),
        )


class TouchAlignmentDialog(QDialog):
    def __init__(self, output_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Touch Alignment Test")
        self.resize(760, 560)
        self.canvas = TouchAlignmentCanvas(output_path)
        self.instructions = QLabel(
            "Touch the highlighted blue target. Gray crosses are completed targets; "
            "red crosses are reported touches."
        )
        self.metrics_label = QLabel("No measurements yet")
        reset = QPushButton("Reset")
        reset.setMinimumHeight(44)
        reset.clicked.connect(self.canvas.reset)
        close = QPushButton("Close")
        close.setMinimumHeight(44)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(reset)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.instructions)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.metrics_label)
        layout.addLayout(buttons)
        self.canvas.changed.connect(self._update_metrics)

    def _update_metrics(self) -> None:
        metrics = self.canvas.metrics()
        if metrics["samples"] == 0:
            self.metrics_label.setText("No measurements yet")
            return
        self.metrics_label.setText(
            f"Targets: {metrics['samples']}/9 · "
            f"median target error {metrics['median_target_error_px']:.1f}px · "
            f"max {metrics['max_target_error_px']:.1f}px · "
            f"mapping error {metrics['max_mapping_error_px']:.2f}px max"
        )
