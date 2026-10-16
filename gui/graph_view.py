"""Evaluation graph component following ShogiGUI style with white background."""

from typing import List, Optional
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont


class GraphView(QWidget):
    """Displays engine evaluation score graph across moves."""

    moveSelected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(95)
        self.setMinimumWidth(400)

        self.scores: List[Optional[int]] = []
        self.score_label = "CAM cp — no engine data"
        self.current_move_idx: int = 0
        self.max_score: int = 2000
        self.min_score: int = -2000

        self.margin_left = 46.0
        self.margin_right = 16.0
        self.margin_top = 10.0
        self.margin_bottom = 14.0

    def set_scores(self, scores: List[int], current_idx: int = 0):
        """Updates evaluation scores and redraws."""
        self.scores = scores
        self.current_move_idx = current_idx
        self.update()

    def set_current_move(self, move_idx: int):
        """Synchronizes current move index indicator."""
        self.current_move_idx = move_idx
        self.update()

    def _val_to_y(self, val: int, plot_y: float, plot_h: float) -> float:
        clamped = max(self.min_score, min(self.max_score, val))
        norm = (clamped - self.min_score) / (self.max_score - self.min_score)
        return plot_y + plot_h - (norm * plot_h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. White Background & Border
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setPen(QPen(QColor("#d1d5db"), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        plot_x = self.margin_left
        plot_y = self.margin_top
        plot_w = max(10.0, self.width() - self.margin_left - self.margin_right)
        plot_h = max(10.0, self.height() - self.margin_top - self.margin_bottom)

        # 2. Draw Y-Axis Labels & Grid Ticks (+2000, +1000, 0, -1000, -2000)
        y_ticks = [2000, 1000, 0, -1000, -2000]
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))

        for val in y_ticks:
            y = self._val_to_y(val, plot_y, plot_h)
            if val == 0:
                painter.setPen(QPen(QColor("#9ca3af"), 1))
                painter.drawLine(int(plot_x), int(y), int(plot_x + plot_w), int(y))
                painter.setPen(QPen(QColor("#4b5563")))
                painter.drawText(
                    QRectF(0, y - 7, self.margin_left - 6, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    "0",
                )
            else:
                painter.setPen(QPen(QColor("#f3f4f6"), 1))
                painter.drawLine(int(plot_x), int(y), int(plot_x + plot_w), int(y))
                painter.setPen(QPen(QColor("#9ca3af")))
                lbl = f"+{val}" if val > 0 else str(val)
                painter.drawText(
                    QRectF(0, y - 7, self.margin_left - 6, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    lbl,
                )

        # Top label
        painter.setPen(QPen(QColor("#111827")))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(plot_x + 4, 1, max(100, plot_w - 8), 14), Qt.AlignmentFlag.AlignLeft, self.score_label)

        total_points = max(len(self.scores), 50)
        dx = plot_w / max(1, total_points - 1)
        y_zero = self._val_to_y(0, plot_y, plot_h)

        # 3. Draw X-Axis Ticks every 10 moves
        painter.setPen(QPen(QColor("#9ca3af"), 1))
        for m in range(0, total_points + 1, 10):
            tx = plot_x + m * dx
            if tx <= plot_x + plot_w:
                tick_h = 5.0 if m % 20 == 0 else 3.0
                painter.drawLine(int(tx), int(y_zero - tick_h), int(tx), int(y_zero + tick_h))

        # 4. Draw Score Curve
        if self.scores:
            pen_curve = QPen(QColor("#1d4ed8"), 2)
            pen_curve.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_curve)

            for i, value in enumerate(self.scores):
                if value is not None:
                    painter.drawEllipse(QRectF(plot_x + i * dx - 2, self._val_to_y(value, plot_y, plot_h) - 2, 4, 4))
            for i in range(len(self.scores) - 1):
                if self.scores[i] is None or self.scores[i + 1] is None:
                    continue
                x1 = plot_x + i * dx
                y1 = self._val_to_y(self.scores[i], plot_y, plot_h)
                x2 = plot_x + (i + 1) * dx
                y2 = self._val_to_y(self.scores[i + 1], plot_y, plot_h)
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # 5. Red Vertical Indicator Line
        if self.current_move_idx >= 0:
            cur_x = plot_x + min(self.current_move_idx, total_points - 1) * dx
            painter.setPen(QPen(QColor("#ef4444"), 1.5))
            painter.drawLine(int(cur_x), int(plot_y), int(cur_x), int(plot_y + plot_h))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            px = event.position().x()
            plot_x = self.margin_left
            plot_w = max(10.0, self.width() - self.margin_left - self.margin_right)

            if plot_x <= px <= plot_x + plot_w:
                total_points = max(len(self.scores), 50)
                dx = plot_w / max(1, total_points - 1)
                move_idx = int(round((px - plot_x) / dx))
                move_idx = max(0, min(len(self.scores) - 1, move_idx))
                self.current_move_idx = move_idx
                self.moveSelected.emit(move_idx)
                self.update()