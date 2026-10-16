"""Analysis-oriented UI widgets used by the main window.

These widgets intentionally do not depend on a concrete engine implementation.
A future analysis backend can update them through their small public APIs.
"""

from typing import Iterable, Mapping, Optional

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.constants import BORDER, PANEL, TEXT, TEXT_MUTED


class WinPercentageWidget(QWidget):
    """Compact Cam/Xanh winning-percentage strip.

    The widget is presentation-only.  Analysis code can call
    ``set_percentages(cam, xanh)`` whenever a new estimate is available.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cam = None
        self._xanh = None
        self.setMinimumHeight(34)
        self.setMaximumHeight(42)
        self.setToolTip("Estimated winning percentage")

    def percentages(self) -> tuple[float, float]:
        return self._cam, self._xanh

    def set_percentages(self, cam: float, xanh: Optional[float] = None):
        cam = max(0.0, min(100.0, float(cam)))
        if xanh is None:
            xanh = 100.0 - cam
        else:
            xanh = max(0.0, min(100.0, float(xanh)))
            total = cam + xanh
            if total > 0:
                cam = cam * 100.0 / total
                xanh = xanh * 100.0 / total
            else:
                cam = xanh = 50.0
        self._cam = cam
        self._xanh = xanh
        self.update()

    def reset(self):
        self._cam = None
        self._xanh = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(QColor(PANEL))
        painter.drawRoundedRect(rect, 5, 5)

        if self._cam is None or self._xanh is None:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "CAM / XANH win probability: N/A — engine WDL unavailable")
            return

        pad = 8.0
        label_w = 92.0
        bar_x = rect.left() + label_w + pad
        bar_w = max(20.0, rect.width() - (label_w * 2.0) - (pad * 2.0))
        bar_y = rect.top() + 8.0
        bar_h = max(14.0, rect.height() - 16.0)
        bar_rect = QRectF(bar_x, bar_y, bar_w, bar_h)

        cam_w = bar_w * self._cam / 100.0
        cam_rect = QRectF(bar_x, bar_y, cam_w, bar_h)
        xanh_rect = QRectF(bar_x + cam_w, bar_y, max(0.0, bar_w - cam_w), bar_h)

        # Use the same side colors already used throughout the board UI.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f28c18"))
        painter.drawRoundedRect(cam_rect, 3, 3)
        painter.setBrush(QColor("#16a34a"))
        painter.drawRoundedRect(xanh_rect, 3, 3)

        # A thin frame keeps the split readable at 0/100 extremes.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#9ca3af"), 1))
        painter.drawRoundedRect(bar_rect, 3, 3)

        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QColor("#c65f00"))
        cam_text = f"Cam {self._cam:.1f}%"
        painter.drawText(
            QRectF(rect.left() + pad, rect.top(), label_w - pad, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            cam_text,
        )

        painter.setPen(QColor("#15803d"))
        xanh_text = f"{self._xanh:.1f}% Xanh"
        painter.drawText(
            QRectF(bar_rect.right() + pad, rect.top(), label_w - pad, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            xanh_text,
        )


class ThinkingInformationWidget(QFrame):
    """ShogiGUI-style table for iterative engine-search information."""

    COLUMNS = ("R", "Time", "Depth", "Nodes", "NPS (computed)", "Value", "Moves")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ThinkingInformation")
        self.setMinimumHeight(130)
        self.setMaximumHeight(230)
        self.setStyleSheet(
            f"""
            QFrame#ThinkingInformation {{
                background: {PANEL};
                border: 1px solid {BORDER};
                border-radius: 5px;
            }}
            QLabel {{
                color: {TEXT};
                background: transparent;
                border: none;
            }}
            QTableWidget {{
                background: #ffffff;
                color: {TEXT};
                border: none;
                gridline-color: #e5e7eb;
                selection-background-color: #eaf5fc;
                selection-color: {TEXT};
                font-size: 11px;
            }}
            QHeaderView::section {{
                background: #f3f4f6;
                color: {TEXT};
                border: none;
                border-right: 1px solid #e5e7eb;
                border-bottom: 1px solid #d1d5db;
                padding: 3px 5px;
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title = QLabel("Thinking information")
        self.title.setStyleSheet(
            f"color: {TEXT}; font-size: 11px; font-weight: 700; padding: 5px 8px;"
            f"border-bottom: 1px solid {BORDER};"
        )
        layout.addWidget(self.title)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table, 1)

        self.metrics = QLabel("WDL: N/A | Neural: N/A | Hybrid: N/A | Confidence: N/A")
        self.metrics.setWordWrap(True); layout.addWidget(self.metrics)

        self.empty_hint = QLabel("Waiting for analysis engine…", self.table.viewport())
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self._sync_empty_hint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.empty_hint.setGeometry(self.table.viewport().rect())

    def _sync_empty_hint(self):
        self.empty_hint.setVisible(self.table.rowCount() == 0)
        self.empty_hint.setGeometry(self.table.viewport().rect())

    def clear(self):
        self.title.setText("Thinking information")
        self.metrics.setText("WDL: N/A | Neural: N/A | Hybrid: N/A | Confidence: N/A")
        self.table.setRowCount(0)
        self._sync_empty_hint()

    def add_entry(
        self,
        r: str = "",
        time: str = "",
        depth: str = "",
        nodes: str = "",
        value: str = "",
        moves: str = "",
        *,
        prepend: bool = True,
        nps: str = "N/A",
    ):
        row = 0 if prepend else self.table.rowCount()
        self.table.insertRow(row)
        values = (r, time, depth, nodes, nps, value, moves)
        for col, value_text in enumerate(values):
            item = QTableWidgetItem(str(value_text))
            if col < 5:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col, item)
        self._sync_empty_hint()

    def set_entries(self, entries: Iterable[Mapping[str, object]]):
        self.table.setRowCount(0)
        for entry in entries:
            self.add_entry(
                r=str(entry.get("r", "")),
                time=str(entry.get("time", "")),
                depth=str(entry.get("depth", "")),
                nodes=str(entry.get("nodes", "")),
                nps=str(entry.get("nps", "N/A")),
                value=str(entry.get("value", "")),
                moves=str(entry.get("moves", "")),
                prepend=False,
            )
        self._sync_empty_hint()

    def update_info(self, info):
        """Update an existing PV-rank row rather than growing an unbounded log."""
        rank = str(info.multipv)
        row = next((r for r in range(self.table.rowCount()) if self.table.item(r, 0) and self.table.item(r, 0).text() == rank), None)
        if row is None:
            row = self.table.rowCount(); self.table.insertRow(row)
        score = 'N/A' if info.score is None else f'{info.score_kind} {info.score:+d} ({info.root_side or info.score_perspective} root, {info.bound})'
        values = (rank, f'{info.time_ms} ms' if info.time_ms is not None else 'N/A', info.depth, info.nodes, info.nps, score, ' '.join(info.pv or []) or 'N/A')
        for col, value in enumerate(values):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem(); self.table.setItem(row, col, item)
            item.setText('N/A' if value is None else str(value))
        self.metrics.setText(f'WDL: {info.wdl if info.wdl is not None else "N/A"} | Neural: {info.neural_value if info.neural_value is not None else "N/A"} | Hybrid: {info.hybrid_value if info.hybrid_value is not None else "N/A"} | Confidence: {info.confidence if info.confidence is not None else "N/A"}')
        self.title.setText('Thinking information — ' + (info.engine_id or 'N/A') + ' | Position ' + (info.position_id[:12] or 'N/A'))
        self._sync_empty_hint()
