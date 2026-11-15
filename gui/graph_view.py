import math
from typing import List, Optional
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath


class GraphView(QWidget):
    """Displays engine evaluation score graph across moves."""

    moveSelected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(105)
        self.setMinimumWidth(400)

        self.scores: List[Optional[int]] = []
        self.score_label = "CAM cp — no engine data"
        self.current_move_idx: int = 0
        self.base_scale: int = 600

        self.margin_left = 46.0
        self.margin_right = 16.0
        self.margin_top = 18.0
        self.margin_bottom = 16.0

    def set_scores(self, scores: List[Optional[int]], current_idx: int = 0):
        """Updates evaluation scores and redraws."""
        self.scores = scores
        self.current_move_idx = current_idx
        self.update()

    def set_current_move(self, move_idx: int):
        """Synchronizes current move index indicator."""
        self.current_move_idx = move_idx
        self.update()

    def _get_scale(self) -> int:
        valid = [abs(v) for v in self.scores if v is not None]
        if not valid:
            return self.base_scale
        m = max(valid)
        if m <= 600:
            return 600
        elif m <= 1000:
            return 1000
        else:
            return int(math.ceil(m / 500.0) * 500)

    def _val_to_y(self, val: int, plot_y: float, plot_h: float, max_s: int) -> float:
        clamped = max(-max_s, min(max_s, val))
        zero_y = plot_y + plot_h * 0.5
        # Up is positive (CAM), Down is negative (XANH)
        return zero_y - (float(clamped) / max_s) * (plot_h * 0.45)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. White Background & Border
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setPen(QPen(QColor("#d1d5db"), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        plot_x = self.margin_left
        plot_y = self.margin_top
        plot_w = max(10.0, float(self.width() - self.margin_left - self.margin_right))
        plot_h = max(10.0, float(self.height() - self.margin_top - self.margin_bottom))

        max_scale = self._get_scale()
        zero_y = plot_y + plot_h * 0.5

        # 2. Draw Y-Axis Labels & Grey Grid Lines (+600, +300, 0, -300, -600 or dynamic)
        y_ticks = [max_scale, max_scale // 2, 0, -max_scale // 2, -max_scale]
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))

        for val in y_ticks:
            y = self._val_to_y(val, plot_y, plot_h, max_scale)
            if val == 0:
                # Crisp grey line at 0
                painter.setPen(QPen(QColor("#9ca3af"), 1.2))
                painter.drawLine(int(plot_x), int(y), int(plot_x + plot_w), int(y))
                painter.setPen(QPen(QColor("#4b5563")))
                painter.drawText(
                    QRectF(0, y - 7, self.margin_left - 6, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    "0",
                )
            else:
                # Clear grey grid line across plot
                painter.setPen(QPen(QColor("#e5e7eb"), 1))
                painter.drawLine(int(plot_x), int(y), int(plot_x + plot_w), int(y))
                painter.setPen(QPen(QColor("#9ca3af")))
                lbl = f"+{val}" if val > 0 else str(val)
                painter.drawText(
                    QRectF(0, y - 7, self.margin_left - 6, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    lbl,
                )

        # Top label (Live / Stored / Move readout)
        label_color = QColor("#111827")
        display_label = self.score_label
        if (
            0 <= self.current_move_idx < len(self.scores)
            and self.scores[self.current_move_idx] is not None
        ):
            c_val = self.scores[self.current_move_idx]
            sign = "+" if c_val > 0 else ""
            adv = "CAM" if c_val > 0 else ("XANH" if c_val < 0 else "Cân bằng")
            display_label = f"Nước {self.current_move_idx}: {sign}{c_val} cp ({adv}) · {self.score_label}"
            if c_val > 0:
                label_color = QColor("#ea580c")
            elif c_val < 0:
                label_color = QColor("#16a34a")

        painter.setPen(QPen(label_color))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(plot_x + 4, 2, max(100.0, plot_w - 8), 14),
            Qt.AlignmentFlag.AlignLeft,
            display_label,
        )

        total_points = max(len(self.scores), 50)
        dx = plot_w / max(1, total_points - 1)

        # 3. Draw X-Axis Ticks (vạch chia trên trục hoành) every 10 moves
        painter.setPen(QPen(QColor("#9ca3af"), 1))
        for m in range(0, total_points + 1, 10):
            tx = plot_x + m * dx
            if tx <= plot_x + plot_w:
                tick_h = 5.0 if m % 20 == 0 else 3.0
                painter.drawLine(int(tx), int(zero_y - tick_h), int(tx), int(zero_y + tick_h))

        # 4. Draw Shaded Fill & Score Curve
        valid_indices = [i for i, v in enumerate(self.scores) if v is not None]
        if len(valid_indices) >= 2:
            fill_path = QPainterPath()
            first_idx = valid_indices[0]
            first_x = plot_x + first_idx * dx
            fill_path.moveTo(first_x, zero_y)
            for i in valid_indices:
                x = plot_x + i * dx
                y = self._val_to_y(self.scores[i], plot_y, plot_h, max_scale)
                fill_path.lineTo(x, y)
            last_idx = valid_indices[-1]
            last_x = plot_x + last_idx * dx
            fill_path.lineTo(last_x, zero_y)
            fill_path.closeSubpath()

            # Shading: Upper region above 0 line is CAM (Soft orange tint)
            painter.save()
            painter.setClipRect(QRectF(plot_x, plot_y, plot_w, max(0.0, zero_y - plot_y)))
            painter.fillPath(fill_path, QBrush(QColor(234, 88, 12, 38)))
            painter.restore()

            # Shading: Lower region below 0 line is XANH (Soft xanh lá tint)
            painter.save()
            painter.setClipRect(QRectF(plot_x, zero_y, plot_w, max(0.0, (plot_y + plot_h) - zero_y)))
            painter.fillPath(fill_path, QBrush(QColor(22, 163, 74, 38)))
            painter.restore()

        if self.scores:
            pen_curve = QPen(QColor("#249dab"), 2)
            pen_curve.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_curve)

            for i in valid_indices:
                x = plot_x + i * dx
                y = self._val_to_y(self.scores[i], plot_y, plot_h, max_scale)
                painter.drawEllipse(QRectF(x - 2, y - 2, 4, 4))

            for i in range(len(self.scores) - 1):
                if self.scores[i] is None or self.scores[i + 1] is None:
                    continue
                x1 = plot_x + i * dx
                y1 = self._val_to_y(self.scores[i], plot_y, plot_h, max_scale)
                x2 = plot_x + (i + 1) * dx
                y2 = self._val_to_y(self.scores[i + 1], plot_y, plot_h, max_scale)
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # 5. Vertical Indicator Line & Marker Dot
        if 0 <= self.current_move_idx:
            cur_x = plot_x + min(self.current_move_idx, total_points - 1) * dx
            painter.setPen(QPen(QColor("#ef4444"), 1.8))
            painter.drawLine(int(cur_x), int(plot_y), int(cur_x), int(plot_y + plot_h))

            if (
                0 <= self.current_move_idx < len(self.scores)
                and self.scores[self.current_move_idx] is not None
            ):
                cur_y = self._val_to_y(self.scores[self.current_move_idx], plot_y, plot_h, max_scale)
                cur_score = self.scores[self.current_move_idx]
                dot_color = QColor("#ea580c") if cur_score > 0 else (QColor("#16a34a") if cur_score < 0 else QColor("#ef4444"))
                painter.setPen(QPen(QColor("#ffffff"), 1.5))
                painter.setBrush(QBrush(dot_color))
                painter.drawEllipse(QPointF(cur_x, cur_y), 4.0, 4.0)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            px = event.position().x()
            plot_x = self.margin_left
            plot_w = max(10.0, float(self.width() - self.margin_left - self.margin_right))

            if plot_x <= px <= plot_x + plot_w:
                total_points = max(len(self.scores), 50)
                dx = plot_w / max(1, total_points - 1)
                move_idx = int(round((px - plot_x) / dx))
                move_idx = max(0, min(len(self.scores) - 1, move_idx))
                self.current_move_idx = move_idx
                self.moveSelected.emit(move_idx)
                self.update()
