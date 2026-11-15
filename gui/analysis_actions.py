"""Shared non-playing Analysis/Consider lifecycle with Continuous Infinite Analysis."""
import time
from weakref import WeakKeyDictionary
from PyQt6.QtCore import QTimer, QSettings
from PyQt6.QtWidgets import QMessageBox
from engine import registry
from engine.pieces import Player
from engine.protocol import export_game, position_id


class AnalysisActions:
    def _init_inspection(self):
        self.analysis_controls = self.thinking_information
        self.thinking_information.setMinimumSize(240, 140)
        self.act_analysis.setText("Phân tích Engine (Analysis)")
        self._evaluation_nodes = WeakKeyDictionary()
        self._pending_graph = False
        self._live_evaluation_node = None
        self._live_analysis_active = False
        self._inspection_error = ""
        self._inspection_mode = None
        self._desired_inspection = None
        self._inspection_restart = False
        self._inspection_valid = False
        self._inspection_position = None
        self._inspection_pid = ""
        self._inspection_best = ""
        self._inspection_started_at = None

        self.thinking_information.btn_toggle.clicked.connect(self._toggle_infinite_analysis)
        self.thinking_information.btn_engine.clicked.connect(self._open_engine_settings)
        self.thinking_information.engine_combo.currentIndexChanged.connect(self._on_analysis_engine_changed)

        self.engine_controller.stateChanged.connect(self._inspection_state)

        self._inspection_timer = QTimer(self)
        self._inspection_timer.setInterval(200)
        self._inspection_timer.timeout.connect(self._flush_evaluations)
        self._inspection_timer.start()

        self._refresh_analysis_engines()

    def _on_analysis_engine_changed(self, index):
        chosen = self.thinking_information.engine_combo.currentData()
        if chosen:
            settings = registry.settings()
            settings.setValue("analysis/engine_id", chosen)
            settings.sync()

    def _refresh_analysis_engines(self):
        combo = self.thinking_information.engine_combo
        selected = combo.currentData() or registry.settings().value("analysis/engine_id", "")
        combo.blockSignals(True)
        combo.clear()
        for entry in registry.load():
            if registry.playable(entry):
                combo.addItem(entry["name"], entry.get("id", entry["path"]))
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

        can_start = combo.count() > 0
        if not getattr(self, "_live_analysis_active", False):
            self.thinking_information.btn_toggle.setEnabled(can_start)
            turn_name = self._current_turn_name()
            if can_start:
                self.thinking_information.lbl_reason.setText(f"Ready for Infinite analysis (Lượt {turn_name}).")
            else:
                self.thinking_information.lbl_reason.setText("No engine selected. Infinite search unavailable.")

    def _current_turn_name(self) -> str:
        if hasattr(self, "game") and hasattr(self.game, "current"):
            return "CAM" if self.game.current.name == "CAM" else "XANH"
        return "CAM"

    def _inspection_key(self):
        from engine.game import _position_hash
        return (id(self.game), id(self.game.current_node), _position_hash(self.game.board, self.game.current))

    def _toggle_infinite_analysis(self):
        if getattr(self, "_live_analysis_active", False) or self.engine_controller.running:
            self._stop_inspection()
        else:
            self._start_infinite_analysis()

    def _on_analysis(self):
        self._toggle_infinite_analysis()

    def _start_infinite_analysis(self):
        if getattr(self, "is_game_active", False):
            self.statusBar().showMessage("Dừng ván cờ trước khi bật Phân tích Engine.", 5000)
            return False

        self._refresh_analysis_engines()
        chosen = self.thinking_information.engine_combo.currentData()
        entry = next((e for e in registry.load() if e.get("id", e["path"]) == chosen and registry.playable(e)), None)
        if not entry:
            self.thinking_information.lbl_reason.setText("Engine không khả dụng. Vào ⚙ Engine để kiểm tra lại.")
            QMessageBox.warning(self, "Engine unavailable", "Chọn và kiểm tra executable engine trong Tools → Engine settings.")
            return False

        try:
            state = export_game(self.game)
            self.engine_controller.set_engine_path(entry["path"], entry.get("args", []), entry.get("options", {}))
        except (ValueError, RuntimeError, KeyError) as exc:
            QMessageBox.warning(self, "Analysis unavailable", str(exc))
            return False

        self.engine_dock.show()
        self.thinking_dock.show()
        self.thinking_dock.raise_()

        self._live_analysis_active = True
        self._desired_inspection = "analysis"
        self._inspection_mode = "analysis"
        self._engine_mode = "analysis"
        self._inspection_restart = False
        self._inspection_valid = True
        self._inspection_position = self._inspection_key()
        self._inspection_pid = position_id(state)
        self._inspection_best = ""
        self._inspection_started_at = time.monotonic()
        self._live_evaluation_node = self.game.current_node

        self.thinking_information.clear_table()
        if hasattr(self, "candidates_widget"):
            self.candidates_widget.clear()
        self.win_percentage.reset()
        self.thinking_information.btn_toggle.setText("Stop")
        turn_name = self._current_turn_name()
        self.thinking_information.lbl_reason.setText(f"Analysis running (Infinite) - lượt {turn_name}.")
        self.act_analysis.setText("Stop Analysis")

        self.engine_controller.options['MultiPV'] = self._desired_analysis_multipv()
        if not self.engine_controller.start_infinite(state):
            self._live_analysis_active = False
            self.thinking_information.btn_toggle.setText("Start")
            self.thinking_information.lbl_reason.setText("Khởi động phân tích vô hạn thất bại.")
            return False
        return True

    def _stop_inspection(self):
        self._live_analysis_active = False
        self._desired_inspection = None
        self._inspection_restart = False
        self._inspection_valid = False
        self._inspection_mode = None
        self._engine_mode = "idle"

        self.thinking_information.btn_toggle.setText("Start")
        turn_name = self._current_turn_name()
        self.thinking_information.lbl_reason.setText(f"Ready for Infinite analysis (Lượt {turn_name}).")
        self.act_analysis.setText("Phân tích Engine (Analysis)")

        if hasattr(self, "board"):
            self.board.clear_engine_arrows()
        if self.engine_controller.running:
            self.thinking_information.lbl_reason.setText("Stopping Analysis; waiting for engine completion.")
            self.engine_controller.stop()

    def _desired_analysis_multipv(self) -> int:
        req = getattr(self.board, "max_engine_arrows", 3)
        if hasattr(self, "candidates_dock") and self.candidates_dock.isVisible():
            req = max(req, 5)
        cap = 5
        defs = getattr(self.engine_controller, "option_definitions", None)
        if isinstance(defs, dict) and "MultiPV" in defs:
            try:
                max_opt = getattr(defs["MultiPV"], "max_val", None)
                if max_opt is not None:
                    cap = max(1, min(cap, int(max_opt)))
            except Exception:
                pass
        return max(1, min(cap, int(req)))

    def _restart_analysis(self):
        """Seamlessly continue continuous infinite analysis on the new board position."""
        if not getattr(self, "_live_analysis_active", False):
            return

        if self.game.is_board_terminal():
            self._stop_inspection()
            self.thinking_information.lbl_reason.setText("Position terminal / game ended.")
            return

        self._inspection_valid = False
        self._inspection_restart = True
        self._inspection_position = self._inspection_key()
        state = export_game(self.game)
        self._inspection_pid = position_id(state)
        self._inspection_best = ""
        self._inspection_started_at = time.monotonic()
        self._live_evaluation_node = self.game.current_node

        self.thinking_information.clear_table()
        if hasattr(self, "candidates_widget"):
            self.candidates_widget.clear()
        turn_name = self._current_turn_name()
        self.thinking_information.lbl_reason.setText(f"Analysis running (Infinite) - lượt {turn_name}.")

        if hasattr(self, "board"):
            self.board.clear_engine_arrows()
        if self.engine_controller.running:
            self.engine_controller.stop()
        else:
            self._inspection_restart = False
            self._inspection_valid = True
            self.engine_controller.options['MultiPV'] = self._desired_analysis_multipv()
            self.engine_controller.start_infinite(state)

    def _inspection_position_changed(self):
        if not getattr(self, "_live_analysis_active", False):
            return
        if getattr(self, "is_game_active", False):
            self._stop_inspection()
            return
        if self._inspection_position != self._inspection_key():
            self._restart_analysis()

    def _inspection_started(self):
        self._inspection_started_at = time.monotonic()
        turn_name = self._current_turn_name()
        self.thinking_information.lbl_reason.setText(f"Analysis running (Infinite) - lượt {turn_name}.")
        self.statusBar().showMessage(f"Engine [{self.thinking_information.engine_combo.currentText()}] is analyzing (Infinite).")

    def _inspection_state(self, state):
        if getattr(self, "_live_analysis_active", False):
            if state == "STOPPING":
                self.thinking_information.lbl_reason.setText("Stopping Analysis; waiting for engine completion.")
            elif state == "SEARCHING":
                turn_name = self._current_turn_name()
                self.thinking_information.lbl_reason.setText(f"Analysis running (Infinite) - lượt {turn_name}.")

    def _accept_inspection_info(self, info):
        return self._inspection_valid and self._inspection_position == self._inspection_key()

    def _extract_arrow_from_info(self, info):
        first_not = info.pv[0] if (info.pv and len(info.pv) > 0) else ""
        if hasattr(info, 'pv_moves') and info.pv_moves and len(info.pv_moves) > 0:
            m = info.pv_moves[0]
            src = getattr(m, 'src', None) if not isinstance(m, dict) else m.get('src')
            dst = getattr(m, 'dst', None) if not isinstance(m, dict) else m.get('dst')
            kind = getattr(m, 'kind', 'single') if not isinstance(m, dict) else m.get('kind', 'single')
            ptype = getattr(m, 'ptype', None) if not isinstance(m, dict) else m.get('ptype')
            return {
                'multipv': info.multipv,
                'src': src,
                'dst': dst,
                'kind': kind,
                'ptype': ptype,
                'notation': first_not,
                'cam': (self.game.current == Player.CAM),
            }
        if first_not:
            for m in self.game.legal_moves():
                if m.notation(self.game.board) == first_not:
                    return {
                        'multipv': info.multipv,
                        'src': m.src,
                        'dst': m.dst,
                        'kind': m.kind,
                        'ptype': getattr(m, 'ptype', None),
                        'notation': first_not,
                        'cam': (self.game.current == Player.CAM),
                    }
        return None

    def _inspection_info(self, info):
        if not self._accept_inspection_info(info):
            return

        if hasattr(self, "board") and getattr(self.board, "show_engine_arrows", True):
            max_arrows = getattr(self.board, "max_engine_arrows", 1)
            if 1 <= info.multipv <= max_arrows:
                arrow_data = self._extract_arrow_from_info(info)
                if arrow_data:
                    self.board.set_engine_arrow(info.multipv, arrow_data)

        if info.multipv == 1:
            self._inspection_best = " ".join(info.pv or [])
            if info.score is not None:
                cam_score = info.score if (info.root_side == "CAM" or info.score_perspective == "CAM") else -info.score
                self.win_percentage.set_score(cam_score, "CAM", best_move=self._inspection_best)
                self._evaluation_nodes[self.game.current_node] = (info.position_id, cam_score)
                self._pending_graph = True
                self._live_evaluation_node = self.game.current_node

        self.thinking_information.update_info(info)
        if hasattr(self, "candidates_widget"):
            self.candidates_widget.update_info(info, self.game)

    def _flush_evaluations(self):
        if getattr(self, "_pending_graph", False):
            self._pending_graph = False
            self._update_history_and_graph()

    def _inspection_bestmove(self, move, text):
        if not self._inspection_valid or self._inspection_position != self._inspection_key():
            return
        if text:
            self._inspection_best = text
            evals = getattr(self, "_evaluation_nodes", {})
            if self.game.current_node in evals:
                self.win_percentage.set_score(evals[self.game.current_node][1], "CAM", best_move=text)

    def _inspection_finished(self, code):
        if getattr(self, "_inspection_restart", False) and getattr(self, "_live_analysis_active", False):
            self._inspection_restart = False
            self._inspection_valid = True
            self.engine_controller.options['MultiPV'] = self._desired_analysis_multipv()
            QTimer.singleShot(0, lambda: self.engine_controller.start_infinite(export_game(self.game)))
        else:
            self._finish_inspection_transition()

    def _finish_inspection_transition(self):
        if getattr(self, "_closing", False):
            return
        if hasattr(self, "board"):
            self.board.clear_engine_arrows()
        if self.engine_controller.running:
            return
        self._flush_evaluations()
        if not getattr(self, "_live_analysis_active", False):
            self.thinking_information.btn_toggle.setText("Start")
            turn_name = self._current_turn_name()
            self.thinking_information.lbl_reason.setText(f"Ready for Infinite analysis (Lượt {turn_name}).")
            self.act_analysis.setText("Phân tích Engine (Analysis)")
        self._update_history_and_graph()
