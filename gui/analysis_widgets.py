"""Analysis-oriented UI widgets used by the main window.

These widgets intentionally do not depend on a concrete engine implementation.
A future analysis backend can update them through their small public APIs.
"""

from typing import Iterable, Mapping, Optional

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPainterPath
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.constants import BORDER, PANEL, TEXT, TEXT_MUTED


class WinPercentageWidget(QWidget):
    """Sleek Shogi/Broadcast-style Winning Percentage Bar (Images 4, 5, 6).

    Calculates winning probability from evaluation score:
        P(CAM) = 1.0 / (1.0 + 10.0 ** (-cam_score / 600.0)) * 100.0
        P(XANH) = 100.0 - P(CAM)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cam: Optional[float] = None
        self._xanh: Optional[float] = None
        self._score_cp: Optional[int] = None
        self._best_move: str = ""
        self.setMinimumSize(200, 36)
        self.setMaximumHeight(16777215)
        self.setToolTip("Xác suất thắng của CAM / XANH")

    def sizeHint(self) -> QSize:
        return QSize(560, 42)

    def percentages(self) -> tuple[Optional[float], Optional[float]]:
        return self._cam, self._xanh

    def set_percentages(
        self,
        cam: float,
        xanh: Optional[float] = None,
        score_cp: Optional[int] = None,
        best_move: str = "",
    ):
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
        if score_cp is not None:
            self._score_cp = score_cp
        if best_move:
            self._best_move = best_move
        self._update_tooltip()
        self.update()

    def set_score(self, score_cp: Optional[int], root_side: str = "CAM", best_move: str = ""):
        """Calculates winning probability directly from centipawns."""
        if score_cp is None:
            self.reset()
            return
        cam_score = score_cp if root_side == "CAM" else -score_cp
        self._score_cp = cam_score
        if best_move:
            self._best_move = best_move

        if abs(cam_score) >= 20000:
            cam_pct = 100.0 if cam_score > 0 else 0.0
        else:
            import math
            # Standard Shogi/Chess logistic conversion (S=600 cp for 1 Long)
            cam_pct = 1.0 / (1.0 + math.pow(10.0, -cam_score / 600.0)) * 100.0

        xanh_pct = 100.0 - cam_pct
        self.set_percentages(cam_pct, xanh_pct, score_cp=cam_score, best_move=best_move)

    def reset(self):
        self._cam = None
        self._xanh = None
        self._score_cp = None
        self._best_move = ""
        self.setToolTip("Xác suất thắng: Chờ dữ liệu từ Engine")
        self.update()

    def _update_tooltip(self):
        if self._cam is not None and self._xanh is not None:
            eval_txt = f"\nĐiểm đánh giá: {self._score_cp:+d} cp" if self._score_cp is not None else ""
            move_txt = f"\nNước tối ưu: {self._best_move}" if self._best_move else ""
            self.setToolTip(f"Xác suất thắng:\n• CAM: {self._cam:.1f}%\n• XANH: {self._xanh:.1f}%{eval_txt}{move_txt}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)

        # Panel container background
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(QColor(PANEL))
        painter.drawRoundedRect(rect, 5.0, 5.0)

        # Placeholder when N/A
        if self._cam is None or self._xanh is None:
            painter.setPen(QColor(TEXT_MUTED))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                "CAM / XANH win probability: N/A — Engine analyzing to calculate",
            )
            return

        # Layout dimensions for Bar & Labels (Matching Images 4, 5, 6)
        label_w = 68.0
        pad = 8.0
        bar_x = rect.left() + label_w + pad
        bar_w = max(30.0, rect.width() - (label_w * 2.0) - (pad * 2.0))
        bar_h = 16.0
        bar_y = rect.top() + (rect.height() - bar_h) / 2.0
        bar_rect = QRectF(bar_x, bar_y, bar_w, bar_h)
        radius = bar_h / 2.0

        # Bar Clip Path (Full rounded pill capsule)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(bar_rect, radius, radius)

        painter.save()
        painter.setClipPath(clip_path)

        # 1. Fill entire bar with XANH background (Xanh lá - Green)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#16a34a"))  # Xanh lá (Lush Emerald Green)
        painter.drawRect(bar_rect)

        # 2. Fill CAM portion from left (Cam - Vibrant Orange)
        cam_w = bar_w * (self._cam / 100.0)
        cam_rect = QRectF(bar_x, bar_y, cam_w, bar_h)
        painter.setBrush(QColor("#ea580c"))  # Cam (Vibrant Orange)
        painter.drawRect(cam_rect)

        # 3. Midpoint tick marker (at 50% line)
        mid_x = bar_x + bar_w * 0.5
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.drawLine(QPointF(mid_x, bar_y), QPointF(mid_x, bar_y + bar_h))

        painter.restore()

        # Thin outer frame around the capsule
        painter.setPen(QPen(QColor("#94a3b8"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bar_rect, radius, radius)

        # 4. Text labels: Left is CAM %, Right is XANH % (Cam & Xanh lá)
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        # CAM Label on Left (Cam)
        painter.setPen(QColor("#ea580c"))
        cam_text = f"CAM {self._cam:.0f}%"
        painter.drawText(
            QRectF(rect.left() + pad, rect.top(), label_w, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            cam_text,
        )

        # XANH Label on Right (Xanh lá)
        painter.setPen(QColor("#16a34a"))
        xanh_text = f"{self._xanh:.0f}% XANH"
        painter.drawText(
            QRectF(rect.right() - label_w - pad, rect.top(), label_w, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            xanh_text,
        )


class ThinkingInformationWidget(QFrame):
    """Engine Analysis panel matching ColongphuongGUI Train layout and styles."""

    COLUMNS = ("R", "Time", "Depth", "Nodes", "Value", "Moves")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dock_analysis_widget")
        self.setMinimumHeight(140)
        self.setStyleSheet(
            f"""
            QFrame#dock_analysis_widget {{
                background: #f8fafc;
                border: 1px solid {BORDER};
                border-radius: 4px;
            }}
            QLabel {{
                color: {TEXT};
                background: transparent;
                border: none;
            }}
            QPushButton {{
                background: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: #f1f5f9;
                border-color: #94a3b8;
            }}
            QPushButton:pressed {{
                background: #e2e8f0;
            }}
            QComboBox {{
                background: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                min-height: 24px;
            }}
            QTableWidget {{
                background: #ffffff;
                color: {TEXT};
                border: 1px solid #e2e8f0;
                border-radius: 3px;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background: #f1f5f9;
                color: #475569;
                border: none;
                border-right: 1px solid #e2e8f0;
                border-bottom: 1px solid #cbd5e1;
                padding: 3px 5px;
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        # Row 1: Engine Combo, ⚙ Engine, Start/Stop, Stretch, Heading
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self.engine_combo = QComboBox()
        self.engine_combo.setObjectName("analysisEngineCombo")
        self.engine_combo.setMinimumHeight(26)
        self.engine_combo.setMinimumWidth(180)
        self.engine_combo.setToolTip("Chọn Engine phân tích từ Engine settings")
        row1.addWidget(self.engine_combo, 0)

        self.btn_engine = QPushButton("⚙ Engine")
        self.btn_engine.setObjectName("analysisEngineSelect")
        self.btn_engine.setMinimumHeight(26)
        self.btn_engine.setToolTip("Mở bảng cài đặt Engine (Engine settings)")
        row1.addWidget(self.btn_engine, 0)

        self.btn_toggle = QPushButton("Start")
        self.btn_toggle.setObjectName("analysisToggle")
        self.btn_toggle.setMinimumHeight(26)
        self.btn_toggle.setMinimumWidth(55)
        self.btn_toggle.setToolTip("Bắt đầu/Dừng phân tích suy luận liên tục")
        row1.addWidget(self.btn_toggle, 0)

        row1.addStretch(1)

        self.lbl_title = QLabel("Time for analysis: Infinite")
        self.lbl_title.setObjectName("analysisTitle")
        self.lbl_title.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row1.addWidget(self.lbl_title, 0)
        layout.addLayout(row1)

        # Row 2: Availability / Status reason
        self.lbl_reason = QLabel("Ready for Infinite analysis (Lượt CAM).")
        self.lbl_reason.setObjectName("analysisAvailability")
        self.lbl_reason.setFont(QFont("Segoe UI", 9))
        self.lbl_reason.setStyleSheet("color: #334155; padding-top: 1px;")
        layout.addWidget(self.lbl_reason)

        # Row 3: Runtime Summary
        self.lbl_summary = QLabel("Time —   Depth —   Nodes —   NPS —")
        self.lbl_summary.setObjectName("analysisRuntimeSummary")
        self.lbl_summary.setFont(QFont("Segoe UI", 9))
        self.lbl_summary.setStyleSheet("color: #64748b; padding-bottom: 2px;")
        layout.addWidget(self.lbl_summary)

        # Row 4: MultiPV Table
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("engineThinkingTable")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 26)
        header.resizeSection(1, 55)
        header.resizeSection(2, 50)
        header.resizeSection(3, 68)
        header.resizeSection(4, 58)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table, 1)

        # Backwards compatibility aliases
        self.engine = self.engine_combo
        self.start = self.btn_toggle
        self.stop = self.btn_toggle
        self.status = self.lbl_reason
        self.position = self.lbl_summary
        self.refresh = self.btn_engine
        self.title = self.lbl_title

    def clear(self):
        self.clear_table()

    def clear_table(self):
        self.table.setRowCount(0)
        self.lbl_summary.setText("Time —   Depth —   Nodes —   NPS —")

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
        values = (r, time, depth, nodes, value, moves)
        for col, value_text in enumerate(values):
            item = QTableWidgetItem(str(value_text))
            if col < 5:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col, item)

    def set_entries(self, entries: Iterable[Mapping[str, object]]):
        self.table.setRowCount(0)
        for entry in entries:
            self.add_entry(
                r=str(entry.get("r", "")),
                time=str(entry.get("time", "")),
                depth=str(entry.get("depth", "")),
                nodes=str(entry.get("nodes", "")),
                value=str(entry.get("value", "")),
                moves=str(entry.get("moves", "")),
                prepend=False,
            )

    def update_info(self, info):
        """Update an existing MultiPV rank row and summary line."""
        rank = str(info.multipv)
        row = next(
            (
                r
                for r in range(self.table.rowCount())
                if self.table.item(r, 0) and self.table.item(r, 0).text() == rank
            ),
            None,
        )
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)

        if info.score is not None:
            if info.score_kind == "mate":
                score_str = f"Mate {info.score}"
            else:
                score_str = f"{info.score:+d} cp"
        else:
            score_str = "N/A"

        time_str = f"{info.time_ms} ms" if info.time_ms is not None else "—"
        depth_str = str(info.depth) if info.depth is not None else "—"
        nodes_str = f"{info.nodes:,}" if info.nodes is not None else "—"
        nps_str = f"{info.nps:,}" if info.nps is not None else "—"
        moves_str = " ".join(info.pv or []) if info.pv else "—"

        values = (
            rank,
            time_str,
            depth_str,
            nodes_str,
            score_str,
            moves_str,
        )
        for col, value in enumerate(values):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(str(value))
            if col < 5:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 4 and info.score is not None:
                color = QColor("#ea580c") if info.score > 0 else (QColor("#16a34a") if info.score < 0 else QColor("#1e293b"))
                item.setForeground(color)

        # Update summary line
        self.lbl_summary.setText(f"Time {time_str}   Depth {depth_str}   Nodes {nodes_str}   NPS {nps_str}")


def _format_coord(pos) -> str:
    if not pos or len(pos) != 2:
        return "-"
    from engine.rules import ROWS, COLS
    r, c = pos
    if 0 <= r < len(ROWS) and 0 <= c < len(COLS):
        return f"{ROWS[r]}{COLS[c]}"
    return "-"


class PossibleMovesWidget(QWidget):
    """Displays all legal rule moves for the current board position."""

    moveDoubleClicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._moves = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.lbl_count = QLabel("Possible moves: 0")
        self.lbl_count.setStyleSheet(f"color: {TEXT}; font-size: 12px; font-weight: 700;")
        layout.addWidget(self.lbl_count)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["R", "Move", "Kind", "Source", "Target"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {PANEL}; border: 1px solid {BORDER}; gridline-color: {BORDER}; font-size: 11px; }}"
            f"QHeaderView::section {{ background: #f1f5f9; border: none; border-bottom: 1px solid {BORDER}; padding: 3px 6px; font-weight: 600; font-size: 11px; color: {TEXT}; }}"
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)

    def _on_cell_double_clicked(self, row: int, _col: int):
        if 0 <= row < len(self._moves):
            self.moveDoubleClicked.emit(self._moves[row])

    def update_moves(self, game) -> None:
        if game is None or game.is_board_terminal():
            self._moves = []
            self.lbl_count.setText("Possible moves: 0")
            self.table.setRowCount(0)
            return

        moves = list(game.legal_moves(allow_nonterminal_analysis=True))
        self._moves = moves
        self.lbl_count.setText(f"Possible moves: {len(moves)}")
        self.table.setRowCount(len(moves))

        kind_labels = {
            "single": "Đơn",
            "team": "Đội",
            "drop": "Thả",
            "rotate": "Xoay",
        }
        for row, mv in enumerate(moves):
            nota = mv.notation(game.board)
            kind_txt = kind_labels.get(mv.kind, mv.kind)
            src_txt = f"Kho ({mv.ptype.name})" if mv.kind == "drop" and mv.ptype else _format_coord(mv.src)
            dst_txt = _format_coord(mv.dst or mv.src)
            vals = (str(row + 1), nota, kind_txt, src_txt, dst_txt)
            for col, val in enumerate(vals):
                item = self.table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row, col, item)
                item.setText(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if col != 1 else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))


class EngineCandidatesWidget(QWidget):
    """Displays Top 5 Engine Candidate Moves (Nước đi đề xuất)."""

    moveDoubleClicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row_moves: dict[int, object] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.lbl_hint = QLabel("Chờ Engine đánh giá (Bấm Phân tích hoặc chạy Engine)")
        self.lbl_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.lbl_hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Nước đi", "Điểm số", "Độ sâu", "Biến chính (PV)"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {PANEL}; border: 1px solid {BORDER}; gridline-color: {BORDER}; font-size: 11px; }}"
            f"QHeaderView::section {{ background: #f1f5f9; border: none; border-bottom: 1px solid {BORDER}; padding: 3px 6px; font-weight: 600; font-size: 11px; color: {TEXT}; }}"
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)

    def _on_cell_double_clicked(self, row: int, _col: int):
        mv = self._row_moves.get(row)
        if mv is not None:
            self.moveDoubleClicked.emit(mv)

    def clear(self):
        self._row_moves.clear()
        self.table.setRowCount(0)
        self.lbl_hint.setText("Chờ Engine đánh giá (Bấm Phân tích hoặc chạy Engine)")

    def update_info(self, info, game=None):
        rank = max(1, int(getattr(info, "multipv", 1) or 1))
        if rank > 5:
            return
        row = rank - 1
        if self.table.rowCount() <= row:
            self.table.setRowCount(row + 1)

        pv_moves = list(getattr(info, "pv_moves", None) or [])
        pv_strs = list(getattr(info, "pv", None) or [])
        first_mv = pv_moves[0] if pv_moves else None
        mv_text = ""
        if first_mv is not None and game is not None:
            try:
                mv_text = first_mv.notation(game.board)
            except Exception:
                mv_text = pv_strs[0] if pv_strs else ""
        elif pv_strs:
            mv_text = pv_strs[0]

        if first_mv is not None:
            self._row_moves[row] = first_mv
        elif pv_strs:
            self._row_moves[row] = pv_strs[0]

        score = getattr(info, "score", None)
        score_kind = getattr(info, "score_kind", "cp")
        if score is None:
            score_str = "-"
        elif score_kind == "mate":
            score_str = f"Mate {score}"
        else:
            sign = "+" if score > 0 else ""
            score_str = f"{sign}{score} cp"

        depth = getattr(info, "depth", None)
        depth_str = f"d{depth}" if depth is not None else "-"
        pv_text = " ".join(pv_strs[:10]) if pv_strs else mv_text

        vals = (str(rank), mv_text or "-", score_str, depth_str, pv_text)
        for col, val in enumerate(vals):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(str(val))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if col < 4 else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
            if col == 2 and score is not None:
                color = QColor("#ea580c") if score > 0 else (QColor("#16a34a") if score < 0 else QColor("#1e293b"))
                item.setForeground(color)

        self.lbl_hint.setText(f"Đề xuất Top {min(5, self.table.rowCount())} (nhấp đúp để đi thử)")

