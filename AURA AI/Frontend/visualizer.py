"""Performant central Aura state visualizer."""
from __future__ import annotations

from enum import Enum

try:
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtGui import QColor, QPainter, QRadialGradient
    from PyQt5.QtWidgets import QWidget
except ImportError:  # pragma: no cover - allows backend imports on servers
    QWidget = object  # type: ignore


class AuraState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    UNDERSTANDING = "UNDERSTANDING"
    THINKING = "THINKING"
    SEARCHING = "SEARCHING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    AWAITING_APPROVAL = "AWAITING APPROVAL"
    PROCESSING_PAYMENT = "PROCESSING PAYMENT"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


if QWidget is not object:
    class AuraVisualizer(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.state = AuraState.IDLE
            self._phase = 0.0
            self.setMinimumSize(280, 280)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(32)

        def set_state(self, state: AuraState | str) -> None:
            try:
                self.state = state if isinstance(state, AuraState) else AuraState(state)
            except ValueError:
                self.state = AuraState.THINKING
            self.update()

        def _tick(self):
            if self.state not in {AuraState.IDLE, AuraState.SUCCESS, AuraState.WARNING, AuraState.ERROR}:
                self._phase = (self._phase + 0.045) % 6.283
                self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            center = self.rect().center()
            radius = min(self.width(), self.height()) * 0.31
            if self.state == AuraState.ERROR:
                base = QColor("#FF7F91")
            elif self.state == AuraState.WARNING or self.state == AuraState.AWAITING_APPROVAL:
                base = QColor("#F6C976")
            elif self.state == AuraState.SUCCESS:
                base = QColor("#65D6A2")
            else:
                base = QColor("#7B83FF")
            pulse = 1.0 + (0.045 * __import__("math").sin(self._phase)) if self.state != AuraState.IDLE else 1.0
            gradient = QRadialGradient(center, radius * 1.9)
            glow = QColor(base); glow.setAlpha(24)
            core = QColor(base); core.setAlpha(210)
            gradient.setColorAt(0.0, core)
            gradient.setColorAt(0.42, glow)
            gradient.setColorAt(1.0, QColor(11, 13, 18, 0))
            painter.setBrush(gradient); painter.setPen(Qt.NoPen)
            painter.drawEllipse(center, int(radius * pulse * 1.85), int(radius * pulse * 1.85))
            painter.setBrush(QColor(base.red(), base.green(), base.blue(), 44))
            painter.drawEllipse(center, int(radius * pulse * 0.98), int(radius * pulse * 0.98))
            painter.setBrush(QColor(base.red(), base.green(), base.blue(), 225))
            painter.drawEllipse(center, int(radius * pulse * 0.42), int(radius * pulse * 0.42))
            painter.setPen(QColor("#F2F4F8"))
            painter.drawText(self.rect().adjusted(0, int(radius * 1.15), 0, 0), Qt.AlignCenter, self.state.value)
else:
    class AuraVisualizer:  # pragma: no cover
        def __init__(self, *args, **kwargs):
            self.state = AuraState.IDLE
        def set_state(self, state):
            self.state = state
