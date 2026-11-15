"""Batch Game Analysis module for ColongphuongGUI_1.

Allows automated analysis of an entire loaded game record:
- Configurable time per move (e.g. 3s) and/or max total time (e.g. 10m)
- Progress tracking with cancellation support
- Automatic evaluation curve generation in GraphView
"""

from __future__ import annotations

import time
from typing import List, Optional

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class BatchAnalysisDialog(QDialog):
    """Configuration dialog for batch game analysis."""

    def __init__(
        self,
        parent: QWidget | None,
        engine_names: List[str],
        current_engine: str,
        total_plies: int,
        current_ply: int,
    ):
        super().__init__(parent)
        self.setWindowTitle("Phân tích toàn bộ kỳ phổ (Game Analysis)")
        self.setMinimumWidth(440)
        self.total_plies = max(1, total_plies)
        self.current_ply = max(0, min(current_ply, self.total_plies - 1))

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Intro banner
        intro = QLabel(
            "Chức năng phân tích tự động: Engine sẽ duyệt qua từng nước đi trong kỳ phổ "
            "theo giới hạn thời gian bạn thiết lập, sau đó xuất toàn bộ đồ thị đánh giá (Evaluation Graph)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(intro)

        # Settings group
        settings_group = QGroupBox("Cài đặt phân tích")
        form = QFormLayout(settings_group)
        form.setSpacing(10)

        # Engine selector
        self.engine_combo = QComboBox()
        for eng in engine_names:
            self.engine_combo.addItem(eng)
        if current_engine in engine_names:
            self.engine_combo.setCurrentText(current_engine)
        form.addRow("Engine phân tích:", self.engine_combo)

        # Time per move
        self.time_per_move_spin = QSpinBox()
        self.time_per_move_spin.setRange(1, 120)
        self.time_per_move_spin.setValue(3)
        self.time_per_move_spin.setSuffix(" giây / nước")
        form.addRow("Thời gian mỗi nước:", self.time_per_move_spin)

        # Max total time
        self.max_total_time_spin = QSpinBox()
        self.max_total_time_spin.setRange(1, 240)
        self.max_total_time_spin.setValue(10)
        self.max_total_time_spin.setSuffix(" phút")
        form.addRow("Tổng thời gian tối đa:", self.max_total_time_spin)

        layout.addWidget(settings_group)

        # Range group
        range_group = QGroupBox("Phạm vi phân tích")
        range_layout = QVBoxLayout(range_group)
        range_layout.setSpacing(6)

        self.btn_group = QButtonGroup(self)
        self.radio_all = QRadioButton(f"Toàn bộ ván cờ (Nước 0 đến {max(0, self.total_plies - 1)} · {self.total_plies} thế cờ)")
        self.radio_all.setChecked(True)
        rem_count = max(1, self.total_plies - self.current_ply)
        self.radio_from_cur = QRadioButton(
            f"Từ nước hiện tại ({self.current_ply}) đến hết ({max(0, self.total_plies - 1)} · {rem_count} thế cờ)"
        )
        self.btn_group.addButton(self.radio_all)
        self.btn_group.addButton(self.radio_from_cur)
        range_layout.addWidget(self.radio_all)
        range_layout.addWidget(self.radio_from_cur)
        layout.addWidget(range_group)

        # Summary info label
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-weight: bold; color: #0f766e;")
        layout.addWidget(self.summary_label)

        def update_summary():
            plies = self.total_plies if self.radio_all.isChecked() else max(1, self.total_plies - self.current_ply)
            sec_per_mv = self.time_per_move_spin.value()
            max_tot_min = self.max_total_time_spin.value()
            est_total_sec = min(plies * sec_per_mv, max_tot_min * 60)
            mins = est_total_sec // 60
            secs = est_total_sec % 60
            self.summary_label.setText(
                f"Dự kiến: {plies} nước · Khoảng {mins}p {secs:02d}s (Tối đa {max_tot_min} phút)"
            )

        self.time_per_move_spin.valueChanged.connect(update_summary)
        self.max_total_time_spin.valueChanged.connect(update_summary)
        self.radio_all.toggled.connect(update_summary)
        self.radio_from_cur.toggled.connect(update_summary)
        update_summary()

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Bắt đầu phân tích (Start)")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy (Cancel)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_settings(self) -> dict:
        return {
            "engine": self.engine_combo.currentText(),
            "time_per_move_sec": self.time_per_move_spin.value(),
            "max_total_min": self.max_total_time_spin.value(),
            "start_ply": 0 if self.radio_all.isChecked() else self.current_ply,
        }


class BatchProgressDialog(QDialog):
    """Progress dialog showing real-time batch analysis state."""

    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None, total_plies: int):
        super().__init__(parent)
        self.setWindowTitle("Đang phân tích ván cờ...")
        self.setMinimumWidth(450)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.status_label = QLabel("Đang khởi tạo phân tích Engine...")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #1e293b;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(1, total_plies))
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.details_label = QLabel("Đã chạy: 00:00 · Dự kiến còn lại: tính toán...")
        self.details_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.details_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_button = QPushButton("Dừng phân tích (Stop)")
        self.cancel_button.setStyleSheet(
            "background-color: #fee2e2; color: #991b1b; font-weight: bold; padding: 5px 15px;"
        )
        self.cancel_button.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_button)
        layout.addLayout(btn_row)

    def update_progress(
        self,
        current_idx: int,
        total: int,
        ply: int,
        move_name: str,
        elapsed_sec: float,
        remaining_sec: float,
        score_text: str = "",
    ):
        self.progress_bar.setValue(current_idx)
        score_display = f" · Điểm: {score_text}" if score_text else ""
        self.status_label.setText(
            f"Nước {ply}/{max(0, total - 1)} [{move_name}]{score_display} ({current_idx}/{total})"
        )

        el_m, el_s = int(elapsed_sec) // 60, int(elapsed_sec) % 60
        rem_m, rem_s = int(max(0, remaining_sec)) // 60, int(max(0, remaining_sec)) % 60
        self.details_label.setText(
            f"Đã chạy: {el_m:02d}:{el_s:02d} · Dự kiến còn lại: {rem_m:02d}:{rem_s:02d}"
        )

    def _on_cancel(self):
        self.status_label.setText("Đang dừng phân tích...")
        self.cancel_button.setEnabled(False)
        self.cancelRequested.emit()


class BatchGameAnalyzer(QObject):
    """Executes batch game analysis across nodes of ColongphuongGUI_1."""

    finished = pyqtSignal(bool, str)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.win = main_window
        self.nodes_to_analyze: list = []
        self.current_step_idx: int = 0
        self.start_time: float = 0.0
        self.time_per_move_sec: int = 3
        self.max_total_sec: int = 600
        self.is_running: bool = False
        self.progress_dialog: Optional[BatchProgressDialog] = None
        self.latest_ply_score: Optional[int] = None
        self.latest_score_text: str = ""

        # Safety timer for move search
        self.move_timer = QTimer(self)
        self.move_timer.setSingleShot(True)
        self.move_timer.timeout.connect(self._on_move_timeout)

    def start(
        self,
        nodes: list,
        time_per_move_sec: int,
        max_total_min: int,
    ):
        if not nodes:
            self.finished.emit(False, "Không có nước đi nào cần phân tích.")
            return

        self.nodes_to_analyze = list(nodes)
        self.time_per_move_sec = max(1, time_per_move_sec)
        self.max_total_sec = max(10, max_total_min * 60)
        self.current_step_idx = 0
        self.start_time = time.time()
        self.is_running = True

        # Stop existing live analysis
        if getattr(self.win, "_live_analysis_active", False):
            self.win._stop_inspection()
        if self.win.engine_controller.running:
            self.win.engine_controller.stop()

        # Show progress dialog
        self.progress_dialog = BatchProgressDialog(self.win, len(self.nodes_to_analyze))
        self.progress_dialog.cancelRequested.connect(self.cancel)
        self.progress_dialog.show()

        # Start analyzing first node
        QTimer.singleShot(150, self._analyze_next_node)

    def cancel(self):
        if not self.is_running:
            return
        self.is_running = False
        self.move_timer.stop()
        if self.win.engine_controller.running:
            self.win.engine_controller.stop()
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        self.finished.emit(False, f"Đã dừng phân tích ván cờ tại nước {self.current_step_idx}.")

    def _analyze_next_node(self):
        if not self.is_running:
            return

        if self.current_step_idx >= len(self.nodes_to_analyze):
            self._finish_all(True)
            return

        elapsed = time.time() - self.start_time
        if elapsed >= self.max_total_sec:
            self._finish_all(False, "Đã đạt giới hạn tổng thời gian tối đa.")
            return

        target_node = self.nodes_to_analyze[self.current_step_idx]
        remaining_count = len(self.nodes_to_analyze) - self.current_step_idx
        remaining_total = max(1.0, self.max_total_sec - elapsed)

        move_time_sec = min(float(self.time_per_move_sec), remaining_total / remaining_count)
        move_time_ms = int(max(300, move_time_sec * 1000))

        # Navigate board to target_node
        self.win.game.go_to_node(target_node)
        self.win.notation_view.set_current_node(target_node)
        self.win.board.reset_transient_state(clear_last_move=True)
        self.win.board._clear_annotations()
        self.win.board.clear_engine_arrows()
        self.win._update_history_and_graph()
        self.win._sync_all()

        # Get move name
        idx_in_history = 0
        if target_node in getattr(self.win, 'history_nodes', []):
            idx_in_history = self.win.history_nodes.index(target_node)
        else:
            idx_in_history = self.current_step_idx

        mv_name = target_node.notation_text or ("Khởi đầu" if idx_in_history == 0 else f"Nước {idx_in_history}")

        est_rem_sec = remaining_count * move_time_sec
        if self.progress_dialog:
            self.progress_dialog.update_progress(
                self.current_step_idx,
                len(self.nodes_to_analyze),
                idx_in_history,
                mv_name,
                elapsed,
                est_rem_sec,
                self.latest_score_text,
            )

        self.latest_ply_score = None
        self.latest_score_text = ""

        # Set MultiPV 1 for batch analysis efficiency
        self.win.engine_controller.options['MultiPV'] = 1

        # Start search
        self.move_timer.start(move_time_ms + 2500)
        self.win.engine_controller.start_search(self.win.game, move_time_ms=move_time_ms)

    def handle_search_info(self, info):
        if not self.is_running:
            return
        if info.multipv == 1 and info.score is not None:
            cam_score = info.score if (info.root_side == "CAM" or info.score_perspective == "CAM") else -info.score
            self.latest_ply_score = cam_score
            sign = "+" if cam_score > 0 else ""
            self.latest_score_text = f"{sign}{cam_score} cp"
            target_node = self.nodes_to_analyze[self.current_step_idx]
            self.win._evaluation_nodes[target_node] = (info.position_id, cam_score)

    def handle_ply_completed(self, _code=0):
        if not self.is_running:
            return
        self.move_timer.stop()

        target_node = self.nodes_to_analyze[self.current_step_idx]
        if self.latest_ply_score is not None:
            pos_id = self.win.game.position_id() if hasattr(self.win.game, 'position_id') else ''
            self.win._evaluation_nodes[target_node] = (pos_id, self.latest_ply_score)
            self.win.win_percentage.set_score(self.latest_ply_score, 'CAM')
        self.win._update_history_and_graph()

        self.current_step_idx += 1
        QTimer.singleShot(30, self._analyze_next_node)

    def _on_move_timeout(self):
        if not self.is_running:
            return
        if self.win.engine_controller.running:
            self.win.engine_controller.stop()
        self.handle_ply_completed()

    def _finish_all(self, success: bool, reason: str = ""):
        self.is_running = False
        self.move_timer.stop()
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        total = len(self.nodes_to_analyze)
        msg = (
            f"Phân tích toàn bộ kỳ phổ hoàn tất ({total} nước đi)."
            if success
            else f"Phân tích hoàn tất một phần ({self.current_step_idx}/{total} nước). {reason}"
        )
        if hasattr(self.win, 'board') and hasattr(self.win, 'engine_controller'):
            self.win.engine_controller.options['MultiPV'] = getattr(self.win.board, 'max_engine_arrows', 3)
        self.win._update_history_and_graph()
        self.finished.emit(success, msg)
