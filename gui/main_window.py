

import os
import time
import uuid
from datetime import datetime
from typing import Optional, List
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLayout,
    QMessageBox,
    QFileDialog,
    QInputDialog,
    QDialog,
    QSplitter,
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QSize
from PyQt6.QtGui import QAction, QKeySequence, QShortcut

from engine.game import Game, MoveNode
from engine.pieces import Player
from engine.notation import LPGFNotation
from engine import registry
from gui.constants import BG, DEFAULT_KYPHO_DIR, get_default_kypho_dir
from gui.widgets import KomadaiWidget, PlayerCardWidget, StackInspectorWidget
from gui.toolbar import ActionToolbar
from gui.board_canvas import BoardCanvas, EngineArrowOverlay
from gui.notation_view import NotationView
from gui.graph_view import GraphView
from gui.edit_position import EditPositionDialog
from gui.analysis_widgets import (
    WinPercentageWidget,
    ThinkingInformationWidget,
    PossibleMovesWidget,
    EngineCandidatesWidget,
)
from gui.engine_controller import EngineController
from gui.match_runtime import MatchClockState, SeriesScore
from gui.settings_dialogs import (
    EngineListDialog,
    GameSettingsDialog,
    ConsiderSettingsDialog,
    HintSettingsDialog,
    MateSettingsDialog,
    OptionsDialog,
    _load_engines,
)

MENU_BAR_STYLE = """
    QMenuBar { 
        background-color: #f8f9fa; 
        color: #212529; 
        border-bottom: 1px solid #dee2e6; 
        font-size: 13px; 
        padding: 2px; 
    }
    QMenuBar::item { 
        background-color: transparent; 
        color: #212529; 
        padding: 5px 10px; 
    }
    QMenuBar::item:selected { 
        background-color: #e9ecef; 
        color: #0d6efd; 
        border-radius: 4px; 
    }
    QMenu {
        background-color: #ffffff;
        color: #212529;
        border: 1px solid #ced4da;
        border-radius: 6px;
        padding: 4px 0px;
    }
    QMenu::item {
        padding: 6px 28px 6px 16px;
        font-size: 13px;
        color: #212529;
    }
    QMenu::item:selected {
        background-color: #0d6efd;
        color: #ffffff;
    }
    QMenu::item:disabled {
        color: #a0a0a0;
    }
    QMenu::separator {
        height: 1px;
        background: #e9ecef;
        margin: 4px 0px;
    }
"""


from gui.recovery_actions import RecoveryActions


from gui.file_actions import FileActions


from gui.docking import DockActions
from gui.layout_manager import LayoutActions
from gui.menus import MenuActions


from gui.analysis_actions import AnalysisActions


from gui.consider_actions import ConsiderActions


from gui.tree_actions import TreeActions

from gui.review_actions import ReviewActions

class _BoardClusterHost(QWidget):
    """Dock content host whose minimumSizeHint stays flexible while children scale inside."""

    def minimumSizeHint(self) -> QSize:
        return QSize(340, 260)

    def sizeHint(self) -> QSize:
        return QSize(720, 520)


class MainWindow(ReviewActions, TreeActions, ConsiderActions, AnalysisActions, MenuActions, DockActions, LayoutActions, FileActions, RecoveryActions, QMainWindow):
    menu_bar_style = MENU_BAR_STYLE
    """Main window integrating board canvas, player cards, toolbar, notation, and scoped bottom graph."""

    def __init__(self):
        super().__init__()
        self.game = Game()
        self.is_game_active: bool = False
        self._position_editable: bool = True
        self._document_dirty = False
        self.record_metadata = {}
        self.current_file_path: Optional[str] = None
        self.history_nodes: List[MoveNode] = []

        self.setWindowTitle("ColongphuongGUI - Practice Mode")
        self.resize(1240, 840)
        self.setStyleSheet(
            f"QMainWindow {{ background-color: {BG}; }}\n"
            "QMainWindow::separator { background: #cbd5e1; width: 5px; height: 5px; }\n"
            "QMainWindow::separator:hover { background: #94a3b8; }\n"
            "QDockWidget { border: 1px solid #cbd5e1; }\n"
            "QDockWidget::title {\n"
            "    background: #d8dee6;\n"
            "    border-bottom: 1px solid #bfc8d4;\n"
            "    padding: 5px 8px;\n"
            "    text-align: left;\n"
            "    font-weight: 600;\n"
            "    color: #1e293b;\n"
            "}\n"
        )

        self._setup_ui()
        self._init_tree_actions()
        self._init_review()
        self._setup_menu_bar()
        self._configure_core_availability()

        # Step 3.1: asynchronous bridge to the local C++ engine.  Analysis is
        # intentionally non-playing in this first integration step: it proves
        # Python/PyQt6 <-> C++ state/move/info transport before Human-vs-AI.
        self.engine_controller = EngineController(self)
        self.engine_controller.searchStarted.connect(self._on_engine_search_started)
        self.engine_controller.infoReceived.connect(self._on_engine_info)
        self.engine_controller.bestMoveReceived.connect(self._on_engine_bestmove)
        self.engine_controller.searchFinished.connect(self._on_engine_search_finished)
        self.engine_controller.errorOccurred.connect(self._on_engine_error)
        self._engine_bestmove_text = ""
        self._engine_mode: str = "idle"
        self._engine_play_move_applied: bool = False
        self._engine_search_started_monotonic: Optional[float] = None
        self._pending_delayed_engine_move = None
        self.game_setup_config = self._load_saved_game_setup_config()

        # Step 3.3/3.4 match runtime: clocks, robust stop/resign handling,
        # autosave, and continuous game series.
        self._match_clock = MatchClockState()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(100)
        self._clock_timer.timeout.connect(self._on_clock_tick)
        self._clock_last_monotonic: Optional[float] = None
        self._series_enabled = False
        self._series_target = 1
        self._series_completed = 0
        self._series_base_board = None
        self._series_base_player = Player.CAM
        self._autosave_file_path: Optional[str] = None
        self._closing = False

        # Step 3.4 hardening: invalidate stale QTimer/engine callbacks between
        # matches and keep a small continuous-series scoreboard.
        self._match_generation = 0
        self._engine_expected_generation: Optional[int] = None
        self._engine_expected_player: Optional[Player] = None
        self._engine_expected_node = None
        self._series_score = SeriesScore()
        self._init_inspection()
        self._init_consider()

        self._update_menu_states()
        self._sync_all()
        self.board.allow_analysis_after_result = True
        self._esc_clear_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_clear_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._esc_clear_shortcut.activated.connect(self.board._clear_annotations)
        app_settings = registry.settings()
        show_arr = bool(app_settings.value("analysis/show_arrows", True, type=bool))
        arr_cnt = int(app_settings.value("analysis/arrow_count", 3))
        self.show_arrows = show_arr
        self.board.set_show_engine_arrows(show_arr)
        self.board.set_max_engine_arrows(arr_cnt)
        if hasattr(self, "act_toggle_arrows"):
            self.act_toggle_arrows.setChecked(show_arr)
        self._init_recovery()
        self._init_layout()
        self._sync_go_back_button()

    def _configure_core_availability(self):
        """GUI rules are bundled in engine/; missing external AI engines are optional."""
        self._missing_engine_paths = sorted({
            str(item['path']) for item in registry.load()
            if item.get('path') and not os.path.isfile(str(item['path']))
        })
        if self._missing_engine_paths:
            self.statusBar().showMessage(
                "Đường dẫn engine phân tích không còn tồn tại — GUI và luật vẫn hoạt động."
            )

    def _warn_missing_external_dependencies(self):
        if not self._missing_engine_paths:
            return
        QMessageBox.warning(
            self, "Thiếu engine phân tích bên ngoài",
            "Một số file engine đã đăng ký không còn tồn tại. "
            "Bạn vẫn có thể dùng bàn cờ, luật và kỳ phổ bình thường.\n\n"
            + "\n".join('• ' + p for p in self._missing_engine_paths[:10])
            + "\n\nHãy sửa đường dẫn tại Tools → Engine settings."
        )

    def _ensure_default_dir(self) -> str:
        target = get_default_kypho_dir()
        os.makedirs(target, exist_ok=True)
        return target

    def _has_game_content(self) -> bool:
        return self.is_game_active or self.game.has_custom_base_position() or bool(self.game.root and self.game.root.children)

    def _update_menu_states(self):
        has_content = self._has_game_content()
        self.act_new.setEnabled(has_content)
        self.act_resign.setEnabled(self.is_game_active)
        self.act_stop.setEnabled(self.is_game_active)
        if hasattr(self, "act_analysis"):
            # Analysis is a separate mode; do not let it compete with an active match.
            self.act_analysis.setEnabled(not self.is_game_active)

    def _load_saved_game_setup_config(self) -> dict:
        s = registry.settings()
        return {
            "cam_controller": str(s.value("game/cam_controller", "Human")),
            "xanh_controller": str(s.value("game/xanh_controller", "Human")),
            "cam_name": str(s.value("game/cam_name", "")),
            "xanh_name": str(s.value("game/xanh_name", "")),
            "cam_hours": int(s.value("game/cam_hours", 0)),
            "cam_minutes": int(s.value("game/cam_minutes", 10)),
            "cam_countdown": int(s.value("game/cam_countdown", 30)),
            "use_max_engine_time": s.value("game/use_max_engine_time", True, type=bool),
            "engine_move_time_ms": int(s.value("game/engine_move_time_ms", 1000)),
            "use_min_engine_time": s.value("game/use_min_engine_time", False, type=bool),
            "engine_min_time_ms": int(s.value("game/engine_min_time_ms", 500)),
            "separate_xanh_time": s.value("game/separate_xanh_time", False, type=bool),
            "xanh_hours": int(s.value("game/xanh_hours", 0)),
            "xanh_minutes": int(s.value("game/xanh_minutes", 10)),
            "xanh_countdown": int(s.value("game/xanh_countdown", 30)),
            "allow_go_back": s.value("game/allow_go_back", False, type=bool),
            "display_thinking_human": s.value("game/display_thinking_human", False, type=bool),
        }

    def _invalidate_match_callbacks(self) -> int:
        self._match_generation += 1
        self._engine_expected_generation = None
        self._engine_expected_player = None
        self._engine_expected_node = None
        self._pending_delayed_engine_move = None
        return self._match_generation

    def _schedule_engine_turn(self, delay_ms: int = 50):
        generation = self._match_generation
        QTimer.singleShot(
            max(0, int(delay_ms)),
            lambda g=generation: self._maybe_start_engine_turn(expected_generation=g),
        )

    def _same_move(self, a, b) -> bool:
        if a is None or b is None:
            return a == b
        return (
            a.kind == b.kind
            and a.src == b.src
            and a.dst == b.dst
            and a.ptype == b.ptype
            and a.facing == b.facing
            and a.rotate_after == b.rotate_after
        )

    def _controller_name_for(self, player: Player) -> str:
        key = "cam_controller" if player == Player.CAM else "xanh_controller"
        value = str(self.game_setup_config.get(key, "Human")).strip()
        return value or "Human"

    def _controller_is_human(self, player: Player) -> bool:
        return self._controller_name_for(player).lower() == "human"

    def _resolve_engine_entry(self, controller_name):
        return next((e for e in _load_engines() if e.get('name') == controller_name and registry.playable(e)), None)

    def _resolve_engine_path(self, controller_name):
        entry = self._resolve_engine_entry(controller_name)
        return entry['path'] if entry else None

    def _engine_move_time_ms(self, player: Player) -> int:
        """Per-move search budget honoring optional max/min bounds and live clock."""
        use_max = bool(self.game_setup_config.get("use_max_engine_time", True))
        use_min = bool(self.game_setup_config.get("use_min_engine_time", False))
        try:
            min_req = max(0, int(self.game_setup_config.get("engine_min_time_ms", 500))) if use_min else 0
        except Exception:
            min_req = 0

        available = self._match_clock.remaining_for(player)
        if use_max:
            try:
                requested = max(100, int(self.game_setup_config.get("engine_move_time_ms", 1000)))
            except Exception:
                requested = 1000
        elif available > 0:
            main_ms = self._match_clock.main_remaining_for(player)
            period_ms = self._match_clock.period_for(player)
            if main_ms > 0:
                requested = max(1000, main_ms // 20 + period_ms, min_req)
            else:
                requested = max(500, available - 300, min_req)
        else:
            requested = max(10000, min_req)

        if available <= 0:
            return requested
        # Keep a safety margin so GUI/process overhead does not flag the engine.
        safe_cap = max(100, available - 250)
        return min(requested, safe_cap)

    def _effective_min_engine_time_ms(self, player: Player) -> int:
        if not bool(self.game_setup_config.get("use_min_engine_time", False)):
            return 0
        try:
            min_ms = max(0, int(self.game_setup_config.get("engine_min_time_ms", 500)))
        except Exception:
            min_ms = 0
        if bool(self.game_setup_config.get("use_max_engine_time", True)):
            try:
                max_ms = max(100, int(self.game_setup_config.get("engine_move_time_ms", 1000)))
                min_ms = min(min_ms, max_ms)
            except Exception:
                pass
        available = self._match_clock.remaining_for(player)
        if available > 0:
            min_ms = min(min_ms, max(0, available - 250))
        return max(0, min_ms)

    def _refresh_active_game_input(self):
        if not self.is_game_active:
            return
        allow_moves = (
            not self.game.is_over()
            and not self.engine_controller.running
            and self._controller_is_human(self.game.current)
        )
        self.board.set_moves_enabled(allow_moves)

    def _maybe_start_engine_turn(self, expected_generation: Optional[int] = None):
        if expected_generation is not None and expected_generation != self._match_generation:
            return False
        if not self.is_game_active or self.game.is_over() or self.engine_controller.running:
            self._refresh_active_game_input()
            return False

        current = self.game.current
        controller = self._controller_name_for(current)
        if controller.lower() == "human":
            self._refresh_active_game_input()
            return False

        engine_path = self._resolve_engine_path(controller)
        if not engine_path:
            self.board.set_moves_enabled(False)
            QMessageBox.warning(
                self,
                "Engine not found",
                f"Engine '{controller}' is not registered in Engine list.",
            )
            return False

        self._engine_mode = "play"
        self._engine_play_move_applied = False
        self._engine_bestmove_text = ""
        self._engine_search_started_monotonic = time.monotonic()
        self.clear_thinking_information()
        if hasattr(self, "candidates_widget"):
            self.candidates_widget.clear()
        self.board.set_moves_enabled(False)

        try:
            entry = self._resolve_engine_entry(controller)
            self.engine_controller.set_engine_path(engine_path, entry.get('args', []), entry.get('options', {}))
        except Exception as exc:
            QMessageBox.warning(self, "Engine", str(exc))
            self._engine_mode = "idle"
            self._refresh_active_game_input()
            return False

        self._engine_expected_generation = self._match_generation
        self._engine_expected_player = current
        self._engine_expected_node = self.game.current_node
        started = self.engine_controller.start_search(
            self.game,
            move_time_ms=self._engine_move_time_ms(current),
            clocks={'camtime': self._match_clock.main_remaining_for(Player.CAM),
                    'xanhtime': self._match_clock.main_remaining_for(Player.XANH),
                    'camperiod': self._match_clock.period_for(Player.CAM),
                    'xanhperiod': self._match_clock.period_for(Player.XANH)},
        )
        if not started:
            self._engine_mode = "idle"
            self._engine_expected_generation = None
            self._engine_expected_player = None
            self._engine_expected_node = None
            self._refresh_active_game_input()
            return False
        return True

    def _other_player(self, player: Player) -> Player:
        return Player.XANH if player == Player.CAM else Player.CAM

    def _configure_match_clock(self):
        cfg = self.game_setup_config
        self._match_clock = MatchClockState()
        self._match_clock.configure_side(
            Player.CAM,
            hours=int(cfg.get("cam_hours", 0)),
            minutes=int(cfg.get("cam_minutes", 10)),
            countdown_s=int(cfg.get("cam_countdown", 30)),
        )
        self._match_clock.configure_side(
            Player.XANH,
            hours=int(cfg.get("xanh_hours", cfg.get("cam_hours", 0))),
            minutes=int(cfg.get("xanh_minutes", cfg.get("cam_minutes", 10))),
            countdown_s=int(cfg.get("xanh_countdown", cfg.get("cam_countdown", 30))),
        )
        self._match_clock.start_turn(self.game.current)
        self._clock_last_monotonic = time.monotonic()
        self._clock_timer.start()
        self._update_runtime_cards()

    def _consume_clock_elapsed(self, player: Optional[Player] = None) -> bool:
        if not self.is_game_active or self._clock_last_monotonic is None:
            return False
        now = time.monotonic()
        elapsed_ms = max(0, int((now - self._clock_last_monotonic) * 1000))
        self._clock_last_monotonic = now
        active = player or self.game.current
        flagged = self._match_clock.consume(active, elapsed_ms)
        if flagged and not bool(self.game_setup_config.get("dont_lose_time", False)):
            self._handle_time_loss(active)
            return True
        return False

    def _on_clock_tick(self):
        if not self.is_game_active or self.game.is_over():
            return
        self._consume_clock_elapsed(self.game.current)
        self._update_runtime_cards()

    def _on_turn_changed(self):
        if not self.is_game_active or self.game.is_over():
            return
        self._match_clock.start_turn(self.game.current)
        self._clock_last_monotonic = time.monotonic()
        self._update_runtime_cards()

    def _handle_time_loss(self, loser: Player):
        if not self.is_game_active or self.game.is_over():
            return
        winner = self._other_player(loser)
        self.game.forfeit(loser, f"{loser.name} thua (Het gio) - {winner.name} thang")
        self.game.current_node.result = self.game.result
        self._finish_current_game("time")

    def _update_runtime_cards(self):
        if not hasattr(self, "card_cam"):
            return

        self.card_cam.set_clock_text(self._match_clock.display(Player.CAM))
        self.card_xanh.set_clock_text(self._match_clock.display(Player.XANH))

        for player, card in ((Player.CAM, self.card_cam), (Player.XANH, self.card_xanh)):
            if self.game.is_over():
                status = "Finished"
            elif not self.is_game_active:
                status = "Stopped"
            elif player != self.game.current:
                status = "Waiting"
            elif self.engine_controller.running and self._engine_mode == "play":
                status = "Thinking..."
            elif self._controller_is_human(player):
                status = "Your turn"
            else:
                status = "Engine turn"
            card.set_runtime_status(status)

    def _setup_series(self):
        self._series_enabled = bool(self.game_setup_config.get("continuous", False))
        self._series_target = max(1, int(self.game_setup_config.get("continuous_games", 1))) if self._series_enabled else 1
        self._series_completed = 0
        self._series_score.reset()
        self._series_base_board, self._series_base_player = self.game.get_base_position()

    def _swap_series_players(self):
        pairs = [
            ("cam_controller", "xanh_controller"),
            ("cam_name", "xanh_name"),
            ("cam_hours", "xanh_hours"),
            ("cam_minutes", "xanh_minutes"),
            ("cam_countdown", "xanh_countdown"),
        ]
        for left, right in pairs:
            self.game_setup_config[left], self.game_setup_config[right] = (
                self.game_setup_config.get(right),
                self.game_setup_config.get(left),
            )

    def _prepare_next_series_game(self, expected_generation: Optional[int] = None):
        if expected_generation is not None and expected_generation != self._match_generation:
            return
        if self._closing or not self._series_enabled or self._series_completed >= self._series_target:
            return
        self._invalidate_match_callbacks()
        if bool(self.game_setup_config.get("after_replacement", False)):
            self._swap_series_players()

        self.game.set_base_position(self._series_base_board.clone(), self._series_base_player)
        if self.game_setup_config.get("draw_moves"):
            self.game.max_plies = int(self.game_setup_config.get("draw_move_limit", 256))
        self.current_file_path = None
        self._autosave_file_path = None
        self._orient_for_setup()
        self.is_game_active = True
        self.board.allow_analysis_after_result = False
        self.board._clear_annotations()
        self.board.reset_transient_state(clear_last_move=True)

        cam_controller = self._controller_name_for(Player.CAM)
        xanh_controller = self._controller_name_for(Player.XANH)
        cam_name = str(self.game_setup_config.get("cam_name", "")).strip()
        xanh_name = str(self.game_setup_config.get("xanh_name", "")).strip()
        self.card_cam.set_player_name(cam_name or cam_controller)
        self.card_xanh.set_player_name(xanh_name or xanh_controller)

        self.notation_view.rebuild_tree(
            self.game.root, self.game.current_node, self.game.board,
            game_result=self.game.result, current_player=self.game.current,
        )
        self._update_history_and_graph()
        self._update_menu_states()
        self._sync_all()
        self._configure_match_clock()
        self.statusBar().showMessage(
            f"Continuous game {self._series_completed + 1}/{self._series_target}: "
            f"Cam [{cam_controller}] vs Xanh [{xanh_controller}] | "
            f"Score {self._series_score.summary()}",
            8000,
        )
        self._schedule_engine_turn(80)

    def _autosave_current_game(self, *, final: bool = False):
        if not bool(self.game_setup_config.get("autosave", False)):
            return
        folder = str(self.game_setup_config.get("autosave_path", "")).strip()
        if not folder:
            return
        try:
            os.makedirs(folder, exist_ok=True)
            if not self._autosave_file_path:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                game_no = self._series_completed + 1
                self._autosave_file_path = os.path.join(folder, f"CLP_{stamp}_{uuid.uuid4().hex[:8]}_G{game_no:03d}.lpgf")
            from engine.records import export_record
            content = export_record(
                game=self.game,metadata=self.record_metadata,
                player_cam=self.card_cam.player_name or "Cam",
                player_xanh=self.card_xanh.player_name or "Xanh",
                format_type="lpgf20",
            )
            from engine.session import atomic_write
            atomic_write(self._autosave_file_path, content)
            if final:
                self.statusBar().showMessage(f"Autosaved: {self._autosave_file_path}", 5000)
        except Exception as exc:
            self.statusBar().showMessage(f"Autosave failed: {exc}", 8000)

    def _adjudicate_engine_failure(self, loser: Player, detail: str):
        """Treat an engine protocol/crash failure as a match loss, not a frozen GUI."""
        if not self.is_game_active or self.game.is_over():
            return
        winner = self._other_player(loser)
        clean = " ".join(str(detail).split())[:180] or "unknown engine error"
        self.game.forfeit(loser, f"{loser.name} thua (Loi engine: {clean}) - {winner.name} thang")
        self.game.current_node.result = self.game.result
        self.statusBar().showMessage(self.game.result, 8000)
        self._finish_current_game("engine_error")

    def _finish_current_game(self, reason: str = "normal"):
        self._invalidate_match_callbacks()
        if self.engine_controller.running:
            self._engine_mode = "idle"
            self.engine_controller.stop()
        self._clock_timer.stop()
        self._clock_last_monotonic = None
        self.is_game_active = False
        self._position_editable = True
        self.board.allow_analysis_after_result = True
        self.board.set_moves_enabled(not self.game.is_board_terminal())
        self._update_menu_states()
        self._update_runtime_cards()
        self._autosave_current_game(final=True)

        self.notation_view.rebuild_tree(
            self.game.root, self.game.current_node, self.game.board,
            game_result=self.game.result, current_player=self.game.current,
        )
        self._sync_all()

        self._series_completed += 1
        self._series_score.record(self.game.result)
        if self._series_enabled and self._series_completed < self._series_target:
            self.statusBar().showMessage(
                f"Game {self._series_completed}/{self._series_target} finished | "
                f"Score {self._series_score.summary()} | {self.game.result}",
                5000,
            )
            generation = self._match_generation
            QTimer.singleShot(
                700,
                lambda g=generation: self._prepare_next_series_game(expected_generation=g),
            )
        else:
            if self._series_target > 1:
                message = (
                    f"Series finished: {self._series_score.summary()}\n\n"
                    f"Last result: {self.game.result or 'Game finished.'}"
                )
                QMessageBox.information(self, "Series Over", message)
            else:
                QMessageBox.information(self, "Game Over", self.game.result or "Game finished.")

    def _stop_match_runtime(self, *, clear_cards: bool = False):
        self._invalidate_match_callbacks()
        self._series_enabled = False
        self._clock_timer.stop()
        self._clock_last_monotonic = None
        self.is_game_active = False
        self._engine_mode = "idle"
        if self.engine_controller.running and not getattr(self, "_live_analysis_active", False):
            self.engine_controller.stop()
        if clear_cards:
            self.card_cam.set_clock_text("")
            self.card_xanh.set_clock_text("")
            self.card_cam.set_runtime_status("")
            self.card_xanh.set_runtime_status("")

    def _on_action_new(self):
        self._leave_review()
        self._tree_undo.clear()
        self._set_force_variation(self.game.current_node,False)
        self._stop_match_runtime(clear_cards=True)
        self.game.reset()
        self._document_dirty = False
        self.record_metadata = {}
        self.current_file_path = None
        self.is_game_active = False
        self.card_cam.clear_card()
        self.card_xanh.clear_card()
        self._update_menu_states()
        self.notation_view.rebuild_tree(self.game.root, self.game.current_node, self.game.board)
        self._update_history_and_graph()
        self.board._clear_annotations()
        self.board.reset_transient_state()
        self._position_editable = True
        self.board.set_moves_enabled(True)
        self._sync_all()
        self.setWindowTitle("ColongphuongGUI - New Game")

    def _on_action_open(self):
        self._open_record()


    def _on_action_save(self):
        if self.current_file_path and self.current_file_path.lower().endswith('.lpgf'):
            self._save_to_file(self.current_file_path)
        else:
            self._on_action_save_as()

    def _on_action_save_as(self):
        default_dir = self._ensure_default_dir()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Record File",
            default_dir,
            "LPGF Record (*.lpgf)",
        )
        if not file_path:
            return

        if not file_path.lower().endswith('.lpgf'):
            file_path += '.lpgf'
        self._save_to_file(file_path)

    def _save_to_file(self, file_path: str):
        fmt = "lpgf20" if file_path.lower().endswith(".lpgf") else None
        self._write_record_file(file_path, format_type=fmt)


    def _edit_picture(self, side: str):
        target_card = self.card_cam if side == "cam" else self.card_xanh
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select Avatar for Player {side.upper()}",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.svg)",
        )
        if file_path:
            target_card.set_picture(file_path)

    def _edit_name(self, side: str):
        target_card = self.card_cam if side == "cam" else self.card_xanh
        new_name, ok = QInputDialog.getText(
            self,
            f"Rename Player {side.upper()}",
            "Enter player name:",
            text=target_card.player_name,
        )
        if ok and new_name.strip():
            target_card.set_player_name(new_name.strip())

    def _edit_ranking(self, side: str):
        target_card = self.card_cam if side == "cam" else self.card_xanh
        new_rank, ok = QInputDialog.getText(
            self,
            f"Rating for Player {side.upper()}",
            "Enter ranking/rating info:",
            text=target_card.player_rank_text or "R: 1905 (4-Dan)",
        )
        if ok and new_rank.strip():
            target_card.set_ranking(new_rank.strip())


    # ----------------------------------------------------
    # Step 3.2 - C++ analysis + engine-play bridge
    # ----------------------------------------------------

    def _on_engine_search_started(self):
        if getattr(self, "_inspection_mode", None):
            self._inspection_started();return
        if self._engine_mode == "analysis":
            self.act_analysis.setText("Stop analysis(A)")
            self.statusBar().showMessage("C++ engine: thinking…")
            return

        controller = self._controller_name_for(self.game.current)
        self.statusBar().showMessage(f"{self.game.current.name} engine [{controller}] is thinking…")
        self._update_runtime_cards()

    def _on_engine_info(self, info):
        if getattr(self, "batch_analyzer", None) and self.batch_analyzer.is_running:
            self.batch_analyzer.handle_search_info(info)
            return
        if getattr(self, "_inspection_mode", None):
            self._inspection_info(info);return
        self.thinking_information.update_info(info)
        if hasattr(self, "candidates_widget"):
            self.candidates_widget.update_info(info, self.game)
        if info.multipv == 1 and info.score is not None:
            cam_score = info.score if (info.root_side == 'CAM' or info.score_perspective == 'CAM') else -info.score
            best_line = ' '.join(info.pv or [])
            self.win_percentage.set_score(cam_score, 'CAM', best_move=best_line)

    def _on_engine_bestmove(self, move, canonical_text: str):
        if getattr(self, "batch_analyzer", None) and self.batch_analyzer.is_running:
            return
        if getattr(self, "_inspection_mode", None):
            self._inspection_bestmove(move, canonical_text);return
        self._engine_bestmove_text = canonical_text

        if self._engine_mode == "analysis":
            if move is None:
                self.statusBar().showMessage("C++ engine: no legal move")
                return

            legal = any(self._same_move(m, move) for m in self.game.legal_moves())
            if legal:
                self.statusBar().showMessage(f"C++ bestmove: {canonical_text} (legal)", 10000)
            else:
                self.statusBar().showMessage(f"C++ bestmove: {canonical_text} (STALE/ILLEGAL)", 10000)
            return

        if self._engine_mode != "play":
            return

        expected_player = self._engine_expected_player
        stale = (
            not self.is_game_active
            or self._engine_expected_generation != self._match_generation
            or expected_player is None
            or self.game.current != expected_player
            or self.game.current_node is not self._engine_expected_node
        )
        if stale:
            self.statusBar().showMessage("Ignored stale engine response", 3000)
            return

        min_ms = self._effective_min_engine_time_ms(expected_player)
        elapsed_ms = 0.0
        if self._engine_search_started_monotonic is not None:
            elapsed_ms = (time.monotonic() - self._engine_search_started_monotonic) * 1000.0
        wait_ms = int(min_ms - elapsed_ms) if min_ms > elapsed_ms else 0

        gen = self._engine_expected_generation
        node = self._engine_expected_node
        if wait_ms > 15:
            self._pending_delayed_engine_move = (gen, expected_player, node, move, canonical_text)
            self.statusBar().showMessage(f"{expected_player.name} waiting min think time…", wait_ms + 500)
            QTimer.singleShot(
                wait_ms,
                lambda g=gen, p=expected_player, n=node, m=move, t=canonical_text: self._apply_engine_play_bestmove(g, p, n, m, t),
            )
            return

        self._apply_engine_play_bestmove(gen, expected_player, node, move, canonical_text)

    def _apply_engine_play_bestmove(self, expected_generation, expected_player, expected_node, move, canonical_text: str):
        self._pending_delayed_engine_move = None
        if self._closing or not self.is_game_active:
            return
        if (
            expected_generation != self._match_generation
            or expected_player is None
            or self.game.current != expected_player
            or self.game.current_node is not expected_node
        ):
            self.statusBar().showMessage("Ignored stale engine response", 3000)
            return

        if move is None:
            if self.game.legal_moves():
                self._adjudicate_engine_failure(expected_player, "engine returned no bestmove")
            else:
                self._finish_current_game("normal")
            return

        legal_move = next((m for m in self.game.legal_moves() if self._same_move(m, move)), None)
        if legal_move is None:
            self._adjudicate_engine_failure(expected_player, f"illegal move {canonical_text}")
            return

        if self._consume_clock_elapsed(self.game.current):
            return

        if not self.game.make_move(legal_move):
            self._adjudicate_engine_failure(expected_player, f"failed to apply {canonical_text}")
            return

        self._document_dirty = True
        self._engine_play_move_applied = True
        self._engine_expected_generation = None
        self._engine_expected_player = None
        self._engine_expected_node = None
        self.board.last_move = legal_move
        self.board.reset_transient_state(clear_last_move=False)
        self.board._clear_annotations()

        self.notation_view.rebuild_tree(
            self.game.root,
            self.game.current_node,
            self.game.board,
            game_result=self.game.result,
            current_player=self.game.current,
        )
        self._update_history_and_graph()
        self._sync_all()
        self._autosave_current_game()

        if self.game.is_over():
            self._finish_current_game("normal")
        else:
            self._on_turn_changed()
            self._refresh_active_game_input()
            self._update_runtime_cards()
            self.statusBar().showMessage(f"Engine played {canonical_text}", 5000)
            if not self.engine_controller.running:
                self._schedule_engine_turn(50)

    def _on_engine_search_finished(self, _exit_code: int):
        if getattr(self, "batch_analyzer", None) and self.batch_analyzer.is_running:
            self.batch_analyzer.handle_ply_completed(_exit_code)
            return
        if getattr(self, "_inspection_mode", None):
            self._inspection_finished(_exit_code);return
        mode = self._engine_mode
        played = self._engine_play_move_applied
        self._engine_mode = "idle"
        self._engine_play_move_applied = False
        self.act_analysis.setText("Analysis(A)")

        if mode == "analysis":
            if self._engine_bestmove_text:
                self.statusBar().showMessage(
                    f"C++ analysis complete - bestmove {self._engine_bestmove_text}", 10000
                )
            return

        if self._pending_delayed_engine_move is not None:
            return
        self._refresh_active_game_input()
        self._update_runtime_cards()
        if played and self.is_game_active and not self.game.is_over():
            self._schedule_engine_turn(50)

    def _on_engine_error(self, message: str):
        if getattr(self, "_inspection_mode", None):
            self._inspection_error = message
            self._inspection_valid = False
            self._desired_inspection = None
            self._inspection_restart = False
            self.analysis_controls.status.setText("ERROR: " + message)
            self.statusBar().showMessage(message, 12000)
            self._inspection_finished(1)
            return
        mode = self._engine_mode
        expected_player = self._engine_expected_player
        expected_generation = self._engine_expected_generation
        self._engine_mode = "idle"
        self._engine_play_move_applied = False
        self._engine_expected_generation = None
        self._engine_expected_player = None
        self._engine_expected_node = None
        self.act_analysis.setText("Analysis(A)")
        self.statusBar().showMessage("C++ engine error", 8000)

        if (
            mode == "play"
            and expected_player is not None
            and expected_generation == self._match_generation
            and self.is_game_active
            and not self.game.is_over()
        ):
            self._adjudicate_engine_failure(expected_player, message)
            return

        if mode == "analysis":
            QMessageBox.warning(self, "C++ Engine", message)

    def _open_engine_settings(self):
        EngineListDialog(self).exec()
        self._refresh_analysis_engines()

    def _open_game_settings(self):
        dialog = GameSettingsDialog(self, allow_start=False)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.game_setup_config = dialog.game_config()
            self._sync_go_back_button()
            self.statusBar().showMessage("Game settings saved", 5000)

    def _open_consider_settings(self):
        ConsiderSettingsDialog(self).exec()

    def _open_batch_analysis(self):
        if self.is_game_active:
            self.statusBar().showMessage("Hãy dừng ván đấu trước khi phân tích toàn bộ kỳ phổ.", 4000)
            return
        from engine import registry
        engines = [e.get('name', e.get('id', '')) for e in registry.load() if registry.playable(e)]
        if not engines:
            QMessageBox.warning(self, "Chưa có Engine", "Không tìm thấy Engine nào khả dụng để phân tích kỳ phổ.\nHãy kiểm tra Tools → Engine settings.")
            return
        cur_engine = self.thinking_information.engine_combo.currentText()
        total_plies = len(self.history_nodes)
        cur_ply = 0
        if self.game.current_node in self.history_nodes:
            cur_ply = self.history_nodes.index(self.game.current_node)

        from gui.batch_analysis import BatchAnalysisDialog, BatchGameAnalyzer
        dlg = BatchAnalysisDialog(self, engines, cur_engine, total_plies, cur_ply)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            settings = dlg.get_settings()
            start_ply = settings['start_ply']
            nodes_to_run = self.history_nodes[start_ply:]
            if not hasattr(self, 'batch_analyzer') or self.batch_analyzer is None:
                self.batch_analyzer = BatchGameAnalyzer(self)
                self.batch_analyzer.finished.connect(self._on_batch_analysis_finished)
            self.batch_analyzer.start(
                nodes_to_run,
                time_per_move_sec=settings['time_per_move_sec'],
                max_total_min=settings['max_total_min'],
            )

    def _on_batch_analysis_finished(self, success: bool, message: str):
        self.statusBar().showMessage(message, 8000)
        QMessageBox.information(self, "Phân tích kỳ phổ", message)

    def _open_hint_settings(self):
        HintSettingsDialog(self).exec()

    def _open_mate_settings(self):
        MateSettingsDialog(self).exec()

    def _open_options(self):
        OptionsDialog(self).exec()

    def _on_edit_position(self):
        """Open the standalone position editor and install the edited root on Apply."""
        self._leave_review()
        self._tree_undo.clear()
        self._stop_match_runtime(clear_cards=False)
        draft = getattr(self, '_recovery_editor', None)
        self._recovery_editor = None
        if draft:
            from engine.notation import _board_from_base_payload
            initial, side = _board_from_base_payload(draft['position'])
        else:
            initial, side = self.game.board.clone(), self.game.current
        dialog = EditPositionDialog(initial, side, self)
        if not draft and dialog.board_canvas.is_flipped != self.board.is_flipped:
            dialog._turn_board()
        if draft:
            if dialog.board_canvas.is_flipped != bool(draft.get('flipped')):
                dialog._turn_board()
            from engine.pieces import PieceType
            dialog.board_canvas.tool_mode = draft.get('tool', 'move')
            if draft.get('palette'):
                owner, ptype = draft['palette']
                dialog.board_canvas.set_palette_piece(Player[owner], PieceType[ptype])
            if draft.get('hand'):
                owner, ptype = draft['hand']
                dialog.board_canvas.set_hand_piece(Player[owner], PieceType[ptype])
            dialog.board_canvas.set_team_mode(bool(draft.get('team')))
            cell = draft.get('selected')
            dialog.board_canvas.selected_cell = tuple(cell) if cell else None
        dialog.board_canvas.positionChanged.connect(self._save_session)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._save_session()
            return

        board, player_to_move = dialog.result_position()
        self._document_dirty = True
        self.record_metadata = {}
        self.game.set_base_position(board, player_to_move)
        self.current_file_path = None
        self.is_game_active = False

        self.board._clear_annotations()
        self.board.reset_transient_state(clear_last_move=True)
        self._position_editable = True
        self.board.set_moves_enabled(True)

        self.notation_view.rebuild_tree(
            self.game.root,
            self.game.current_node,
            self.game.board,
            game_result=self.game.result,
            current_player=self.game.current,
        )
        self._update_history_and_graph()
        self._update_menu_states()
        self._sync_all()
        self.setWindowTitle("ColongphuongGUI - Edited Position")

    def _on_start_game(self):
        """Open the Game setup window; only Start actually begins a match."""
        self._leave_review()
        self._tree_undo.clear()
        dialog = GameSettingsDialog(self, allow_start=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.game_setup_config = dialog.game_config()
        self._sync_go_back_button()
        if not dialog.start_requested:
            self.statusBar().showMessage("Game settings saved", 5000)
            return

        self._stop_match_runtime(clear_cards=False)

        # Standard opening resets the whole game.  "This position" promotes
        # the currently displayed board to a fresh root, which is also useful
        # after Edit position.
        if self.game_setup_config.get("start_position") == "this":
            self.game.set_base_position(self.game.board.clone(), self.game.current)
        else:
            self.game.reset()

        if self.game_setup_config.get("draw_moves"):
            self.game.max_plies = int(self.game_setup_config.get("draw_move_limit", 256))
        self.record_metadata = {}
        self._document_dirty = True
        self.current_file_path = None
        self.is_game_active = True
        self.board.allow_analysis_after_result = False
        self.board._clear_annotations()
        self.board.reset_transient_state(clear_last_move=True)
        self._position_editable = True
        self.board.set_moves_enabled(True)

        cam_controller = str(self.game_setup_config.get("cam_controller", "Human"))
        xanh_controller = str(self.game_setup_config.get("xanh_controller", "Human"))
        cam_name = str(self.game_setup_config.get("cam_name", "")).strip()
        xanh_name = str(self.game_setup_config.get("xanh_name", "")).strip()
        self.card_cam.set_player_name(cam_name or cam_controller)
        self.card_xanh.set_player_name(xanh_name or xanh_controller)

        self.notation_view.rebuild_tree(
            self.game.root,
            self.game.current_node,
            self.game.board,
            game_result=self.game.result,
            current_player=self.game.current,
        )
        self._update_history_and_graph()
        self._update_menu_states()
        self._sync_all()
        self.setWindowTitle("ColongphuongGUI - Game")
        self.statusBar().showMessage(
            f"Game started: Cam [{cam_controller}] vs Xanh [{xanh_controller}]",
            10000,
        )
        self._orient_for_setup()
        self._setup_series()
        self._configure_match_clock()
        self._schedule_engine_turn(50)

    def _on_stop_game(self):
        if self.is_game_active or self.engine_controller.running:
            self._stop_match_runtime(clear_cards=False)
            self._position_editable = True
            self.board.allow_analysis_after_result = True
            self.board.set_moves_enabled(not self.game.is_board_terminal())
            self.card_cam.set_runtime_status("Stopped")
            self.card_xanh.set_runtime_status("Stopped")
            self._update_menu_states()
            self._sync_go_back_button()
            self._autosave_current_game(final=True)
            QMessageBox.information(self, "Stop", "Match stopped.")

    def _on_resign(self):
        """Triggered on Resign menu action or toolbar flag button click."""
        if self.is_game_active and not self.game.is_over():
            if self.engine_controller.running:
                self._engine_mode = "idle"
                self.engine_controller.stop()
            if self._consume_clock_elapsed(self.game.current):
                return
            self.game.resign()
            self._finish_current_game("resign")

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        outer_layout = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(10, 8, 10, 10)
        outer_layout.setSpacing(0)

        # ----------------------------------------------------
        # BOARD AREA CONTENT
        # ----------------------------------------------------
        self.win_percentage = WinPercentageWidget()

        # Keep the board, both komadai and the action toolbar in one
        # centered, resize-coupled cluster rather than stretching BoardCanvas
        # independently between fixed-width side panels.
        self.board_row_widget = _BoardClusterHost()
        self.board_row = QHBoxLayout(self.board_row_widget)
        self.board_row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.board_row.setContentsMargins(0, 0, 0, 0)
        # A compact, constant seam: komadai -> toolbar -> board -> komadai.
        self.board_row.setSpacing(6)
        self._cluster_update_pending = False
        self.board_row_widget.installEventFilter(self)

        self.left_panel_widget = QWidget()
        self.left_col = QVBoxLayout(self.left_panel_widget)
        self.left_col.setSpacing(6)
        self.right_panel_widget = QWidget()
        self.right_sub_col = QVBoxLayout(self.right_panel_widget)
        self.right_sub_col.setSpacing(6)

        self.komadai_xanh = KomadaiWidget(side="xanh")
        self.komadai_cam = KomadaiWidget(side="cam")
        self.card_cam = PlayerCardWidget(side="cam", side_symbol="☗")
        self.card_xanh = PlayerCardWidget(side="xanh", side_symbol="☖")
        self.card_cam.installEventFilter(self)
        self.card_xanh.installEventFilter(self)

        self.komadai_xanh.pieceSelected.connect(self._on_hand_piece_selected)
        self.komadai_cam.pieceSelected.connect(self._on_hand_piece_selected)

        self.board = BoardCanvas(self.game)
        self.toolbar = ActionToolbar()
        self.board.set_toolbar(self.toolbar)
        self.board.pieceSelected.connect(self.toolbar.set_piece_selected_state)
        self.board.moveMade.connect(self._on_move_made)
        self.toolbar.btn_resign.clicked.connect(self._on_resign)
        self.toolbar.goBackClicked.connect(self._on_go_back_clicked)
        self.board.geometryUpdated.connect(self._sync_side_margins)

        self._arrange_side_panels(is_flipped=False)

        self.board_row.addStretch(1)
        self.board_row.addWidget(self.left_panel_widget, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.board_row.addWidget(self.board, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.board_row.addWidget(self.right_panel_widget, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.board_row.addStretch(1)

        self.arrow_overlay = EngineArrowOverlay(
            self.board_row_widget, self.board, self.komadai_cam, self.komadai_xanh
        )
        self.board._overlay_active = True
        self.board.engineArrowsChanged.connect(self.arrow_overlay.update)
        self.arrow_overlay.show()
        self.arrow_overlay.raise_()

        # Evaluation graph is normally compact, but must be allowed to grow
        # vertically when it lives in the lower splitter.
        self.graph_view = GraphView()
        self.graph_view.setMinimumHeight(95)
        self.graph_view.setMaximumHeight(16777215)
        self.graph_view.moveSelected.connect(self._on_graph_move_selected)

        self.thinking_information = ThinkingInformationWidget()
        self.thinking_information.setMinimumHeight(95)
        self.thinking_information.setMaximumHeight(16777215)

        self.candidates_widget = EngineCandidatesWidget()
        self.candidates_widget.setMinimumHeight(95)
        self.candidates_widget.setMaximumHeight(16777215)
        self.candidates_widget.moveDoubleClicked.connect(self._on_suggested_move_played)

        self.possible_moves_widget = PossibleMovesWidget()
        self.possible_moves_widget.setMinimumHeight(95)
        self.possible_moves_widget.setMaximumHeight(16777215)
        self.possible_moves_widget.moveDoubleClicked.connect(self._on_suggested_move_played)

        # ----------------------------------------------------
        # NOTATION AREA
        # ----------------------------------------------------
        self.notation_container = QWidget()
        notation_col = QVBoxLayout(self.notation_container)
        notation_col.setContentsMargins(0, 0, 0, 0)
        notation_col.setSpacing(8)

        self.stack_inspector = StackInspectorWidget()
        self.notation_view = NotationView()
        # Let the splitter, not the old 340px cap, determine the panel width.
        self.stack_inspector.setMaximumWidth(16777215)
        self.notation_view.setMaximumWidth(16777215)
        self.notation_view.node_selected.connect(self._on_node_selected)

        notation_col.addWidget(self.stack_inspector)
        notation_col.addWidget(self.notation_view, stretch=1)
        self.board.cellInspected.connect(self._on_cell_inspected)

        self._setup_docks()
        self._schedule_cluster_update()

    def _style_splitter(self, splitter: QSplitter):
        """Give splitters a subtle, easy-to-grab divider."""
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(5)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #d9dee5; }"
            "QSplitter::handle:hover { background: #94a3b8; }"
        )

    def _on_thinking_visibility_changed(self, visible):
        self.thinking_dock.setVisible(bool(visible))

    # ----------------------------------------------------
    # Analysis UI bridge.  A future engine backend can call these methods
    # without knowing how the widgets are implemented.
    # ----------------------------------------------------
    def set_win_percentages(self, cam: float, xanh: Optional[float] = None):
        self.win_percentage.set_percentages(cam, xanh)

    def clear_thinking_information(self):
        self.thinking_information.clear()

    def add_thinking_information(
        self,
        r: str = "",
        time: str = "",
        depth: str = "",
        nodes: str = "",
        value: str = "",
        moves: str = "",
    ):
        self.thinking_information.add_entry(
            r=r, time=time, depth=depth, nodes=nodes, value=value, moves=moves
        )

    def _update_history_and_graph(self):
        """Builds linear node list and refreshes graph."""
        # Follow the variation containing current_node, not always children[0].
        nodes: List[MoveNode] = []
        curr = self.game.current_node
        while curr is not None:
            nodes.append(curr)
            curr = curr.parent
        nodes.reverse()
        self.history_nodes = nodes

        current_idx = 0
        for i, n in enumerate(self.history_nodes):
            if n == self.game.current_node:
                current_idx = i
                break

        evaluations = getattr(self, '_evaluation_nodes', {})
        scores = [evaluations[n][1] if n in evaluations else None for n in self.history_nodes]
        live = getattr(self, '_live_evaluation_node', None) is self.game.current_node and bool(getattr(self, '_inspection_mode', None))
        self.graph_view.score_label = ('CAM cp — live current position; other points stored' if live else 'CAM cp — stored results (gaps = N/A)') if any(v is not None for v in scores) else 'CAM cp — no engine data'
        self.graph_view.set_scores(scores, current_idx=current_idx)

        # Synchronize winning percentage bar for the selected move
        if self.game.current_node in evaluations:
            self.win_percentage.set_score(evaluations[self.game.current_node][1], 'CAM')
        elif not getattr(self, '_inspection_mode', None):
            self.win_percentage.reset()

    def _on_graph_move_selected(self, move_idx: int):
        if 0 <= move_idx < len(self.history_nodes):
            target_node = self.history_nodes[move_idx]
            self._on_node_selected(target_node)

    def _on_cell_inspected(self, cell, stack_pieces):
        if not cell or not stack_pieces:
            self.stack_inspector.clear()
            return

        rows, cols = "abcdefghi", "987654321"
        coord_name = f"{rows[cell[0]]}{cols[cell[1]]}"
        self.stack_inspector.set_stack(
            stack_pieces,
            is_flipped=getattr(self.board, "is_flipped", False),
            coord_name=coord_name,
        )

    @staticmethod
    def _cluster_dimensions(cell: int, *, toolbar: bool = True, card_width: int = 0):
        """Compute the whole tightly-packed board cluster from one cell size.

        Do not reserve 180px for each komadai when player cards are hidden:
        that was the empty space between CAM and the action toolbar.
        """
        item = max(28, min(80, round(cell * 0.84)))
        stand_width = 3 * item + 2 * 4 + 2 * 6
        side_width = max(stand_width, card_width)
        left_margin = BoardCanvas.toolbar_margin_for_cell(cell) if toolbar else 16
        board_width = 9 * cell + left_margin + 24 + 8
        board_height = 9 * cell + 24 + 8
        return board_width, board_height, side_width

    def _schedule_cluster_update(self):
        if getattr(self, '_cluster_update_pending', False):
            return
        self._cluster_update_pending = True
        QTimer.singleShot(0, self._update_board_cluster)

    def _update_board_cluster(self):
        self._cluster_update_pending = False
        if not hasattr(self, 'board_row_widget'):
            return
        available_w = self.board_row_widget.width()
        available_h = self.board_row_widget.height()
        if available_w < 1 or available_h < 1:
            return

        # Hidden cards must not consume width. When a player profile is shown,
        # keep enough room for its existing 180px card without overlapping.
        card_width = 180 if not (self.card_cam.isHidden() and self.card_xanh.isHidden()) else 0
        toolbar_on = self.board.show_toolbar
        row_spacing = self.board_row.spacing()
        # The two stretch spacers use no width; there are four QHBox gaps.
        target_cell = 28
        for cell in range(28, 128):
            bw, bh, sw = self._cluster_dimensions(cell, toolbar=toolbar_on, card_width=card_width)
            if bw + 2 * sw + 4 * row_spacing + 8 > available_w or bh + 8 > available_h:
                break
            target_cell = cell
        board_w, board_h, side_w = self._cluster_dimensions(
            target_cell, toolbar=toolbar_on, card_width=card_width
        )
        desired_board = (board_w, board_h)
        if (self.board.width(), self.board.height()) != desired_board:
            self.board.setFixedSize(*desired_board)
        for side_panel in (self.left_panel_widget, self.right_panel_widget):
            if (side_panel.width(), side_panel.height()) != (side_w, board_h):
                side_panel.setFixedSize(side_w, board_h)

        # Scale komadai pieces and stand with the board cell size. The panel
        # side (player ownership) does not change; only the view is resized.
        self.board._update_geometry()
        actual_cell = self.board.cell_size
        self.komadai_cam.set_scale(actual_cell)
        self.komadai_xanh.set_scale(actual_cell)
        self._sync_side_margins()
        if hasattr(self, 'arrow_overlay') and self.arrow_overlay:
            self.arrow_overlay.setGeometry(self.board_row_widget.rect())
            self.arrow_overlay.raise_()
            self.arrow_overlay.update()

    def eventFilter(self, watched, event):
        if (any(watched is getattr(self, name, None) for name in ('board_row_widget', 'card_cam', 'card_xanh'))
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide)):
            self._schedule_cluster_update()
        return super().eventFilter(watched, event)

    def _sync_side_margins(self):
        if self.board.board_rect.width() > 0:
            # Also respond when coordinates/toolbar visibility changes the
            # square size without resizing the outer window.
            for stand in (self.komadai_cam, self.komadai_xanh):
                stand.set_scale(self.board.cell_size)
            top_offset = max(0, round(self.board.board_rect.y()))
            bottom_offset = max(0, round(self.board.height() - self.board.board_rect.bottom()))
            for layout in (self.left_col, self.right_sub_col):
                margins = layout.contentsMargins()
                if (margins.top(), margins.bottom()) != (top_offset, bottom_offset):
                    layout.setContentsMargins(0, top_offset, 0, bottom_offset)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_cluster_update()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_cluster_update()

    def _clear_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def _arrange_side_panels(self, is_flipped: bool):
        self._clear_layout(self.left_col)
        self._clear_layout(self.right_sub_col)

        if not is_flipped:
            self.left_col.addWidget(
                self.komadai_cam,
                alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            )
            self.left_col.addStretch(1)
            self.left_col.addWidget(self.card_cam, alignment=Qt.AlignmentFlag.AlignBottom)

            self.right_sub_col.addWidget(self.card_xanh, alignment=Qt.AlignmentFlag.AlignTop)
            self.right_sub_col.addStretch(1)
            self.right_sub_col.addWidget(
                self.komadai_xanh,
                alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            )
        else:
            self.left_col.addWidget(
                self.komadai_xanh,
                alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            )
            self.left_col.addStretch(1)
            self.left_col.addWidget(self.card_xanh, alignment=Qt.AlignmentFlag.AlignBottom)

            self.right_sub_col.addWidget(self.card_cam, alignment=Qt.AlignmentFlag.AlignTop)
            self.right_sub_col.addStretch(1)
            self.right_sub_col.addWidget(
                self.komadai_cam,
                alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            )

    def set_bottom_player(self, player):
        from engine.setup import flipped_for_bottom
        if self.board.is_flipped != flipped_for_bottom(player):
            self._on_turn_board()

    def _orient_for_setup(self):
        from engine.setup import bottom_for_setup
        bottom = bottom_for_setup(self.game_setup_config)
        if bottom is not None:
            self.set_bottom_player(bottom)

    def _on_turn_board(self):
        self.board.toggle_flip()
        is_flipped = self.board.is_flipped
        self._arrange_side_panels(is_flipped)
        self.komadai_cam.set_flipped(is_flipped)
        self.komadai_xanh.set_flipped(is_flipped)
        self._sync_all()

    def _on_hand_piece_selected(self, player_side: str, ptype):
        current_side = "xanh" if self.game.current == Player.XANH else "cam"
        if player_side == current_side:
            self.board.select_hand_piece(ptype)

    def _sync_all(self):
        self.komadai_cam.update_counts(self.game.board, Player.CAM)
        self.komadai_xanh.update_counts(self.game.board, Player.XANH)

        if not self.board.selected_hand_piece:
            self.komadai_cam.clear_selection()
            self.komadai_xanh.clear_selection()

        self._sync_side_margins()
        self.board.update()
        if hasattr(self, "possible_moves_widget"):
            self.possible_moves_widget.update_moves(self.game)
        self._sync_go_back_button()
        self._schedule_cluster_update()
        self._inspection_position_changed()
        self._review_position_changed()
        self._save_session()

    def _on_move_made(self, move):
        self._tree_undo.clear()
        self._document_dirty = True
        if self.engine_controller.running and not getattr(self, "_live_analysis_active", False):
            self._engine_mode = "idle"
            self._engine_expected_generation = None
            self._engine_expected_player = None
            self._engine_expected_node = None
            self.engine_controller.stop()
        self._update_menu_states()
        self.notation_view.rebuild_tree(
            self.game.root,
            self.game.current_node,
            self.game.board,
            game_result=self.game.result,
            current_player=self.game.current,
        )
        self._update_history_and_graph()
        self._sync_all()
        self._autosave_current_game()

        if self.game.is_over():
            self._finish_current_game("normal")
            return

        if self.is_game_active:
            self._on_turn_changed()
            self._schedule_engine_turn(50)

    def _on_node_selected(self, node: MoveNode):
        if self.is_game_active:
            self.notation_view.set_current_node(self.game.current_node)
            self.statusBar().showMessage("Stop the active game before browsing move history.", 4000)
            return
        if self.engine_controller.running:
            self.engine_controller.stop()
        # Preserve an explicit Stop/pause while navigating the history tree,
        # without permanently locking moves after visiting a terminal node.
        allow_if_ongoing = self.board.moves_enabled or getattr(self, "_position_editable", False) or (not self.is_game_active)
        if getattr(self, "_review_active", False):
            allow_if_ongoing = False
        self.game.go_to_node(node)
        self.notation_view.set_current_node(node)
        self.board.reset_transient_state(clear_last_move=True)
        self.board._clear_annotations()
        self.board.allow_analysis_after_result = not self.is_game_active
        self.board.set_moves_enabled(bool(allow_if_ongoing) and not self.game.is_board_terminal())
        self._update_history_and_graph()
        self._update_menu_states()
        self._sync_all()

    def _on_toggle_engine_arrows(self, checked: bool):
        self.show_arrows = bool(checked)
        if hasattr(self, "board"):
            self.board.set_show_engine_arrows(bool(checked))
        settings = registry.settings()
        settings.setValue("analysis/show_arrows", bool(checked))
        settings.sync()

    def _on_suggested_move_played(self, move_or_str):
        if getattr(self, "_review_active", False):
            return
        if self.is_game_active and (self.engine_controller.running or not self._controller_is_human(self.game.current)):
            return
        allow_nonterm = not self.is_game_active
        if allow_nonterm and self.game.is_board_terminal():
            return
        if not allow_nonterm and self.game.is_over():
            return

        legal = self.game.legal_moves(allow_nonterminal_analysis=allow_nonterm)
        target_mv = None
        if isinstance(move_or_str, str):
            text = move_or_str.strip()
            target_mv = next((m for m in legal if m.notation(self.game.board) == text), None)
        else:
            target_mv = next((m for m in legal if self._same_move(m, move_or_str)), None)
        if target_mv is None:
            return
        if self.is_game_active and self._consume_clock_elapsed(self.game.current):
            return
        if not self.game.commit_prevalidated_move(
            target_mv,
            allow_nonterminal_analysis=allow_nonterm,
        ):
            return
        self.board.last_move = target_mv
        self.board.reset_transient_state(clear_last_move=False)
        self.board._clear_annotations()
        self._on_move_made(target_mv)

    def _sync_go_back_button(self):
        if not hasattr(self, "toolbar") or not hasattr(self.toolbar, "set_go_back_visible"):
            return
        self.toolbar.set_go_back_visible(True)
        allow = bool(self.game_setup_config.get("allow_go_back", False))
        has_parent = self.game.current_node is not None and self.game.current_node.parent is not None
        can_undo = allow and has_parent and not getattr(self, "_review_active", False)
        if self.is_game_active and not (
            self._controller_is_human(Player.CAM) or self._controller_is_human(Player.XANH)
        ):
            can_undo = False
        self.toolbar.set_go_back_enabled(can_undo)
        self.toolbar.update_scale(self.board.cell_size if hasattr(self, "board") else 64)

    def _on_go_back_clicked(self):
        if getattr(self, "_review_active", False):
            return
        if not bool(self.game_setup_config.get("allow_go_back", False)):
            return
        cur = self.game.current_node
        if cur is None or cur.parent is None:
            return

        if not self.is_game_active:
            self._on_node_selected(cur.parent)
            return

        cur_is_human = self._controller_is_human(self.game.current)
        other_is_human = self._controller_is_human(self._other_player(self.game.current))
        was_engine_waiting = self.engine_controller.running or (self._pending_delayed_engine_move is not None)
        if was_engine_waiting:
            self._invalidate_match_callbacks()
            if self.engine_controller.running:
                self._engine_mode = "idle"
                self.engine_controller.stop()
            steps = 1
        elif cur_is_human and not other_is_human and cur.parent.parent is not None:
            steps = 2
        else:
            steps = 1

        target = cur
        prune_child = None
        for _ in range(steps):
            if target.parent is None:
                break
            prune_child = target
            target = target.parent

        self.game.go_to_node(target)
        if prune_child is not None and prune_child in target.children:
            try:
                target.children.remove(prune_child)
            except ValueError:
                pass

        self._clock_last_monotonic = time.monotonic()
        self.board.reset_transient_state(clear_last_move=True)
        self.board._clear_annotations()
        self.notation_view.rebuild_tree(
            self.game.root,
            self.game.current_node,
            self.game.board,
            game_result=self.game.result,
            current_player=self.game.current,
        )
        self._update_history_and_graph()
        self._refresh_active_game_input()
        self._update_runtime_cards()
        self._sync_all()
        self.statusBar().showMessage("Returned to previous move.", 3000)
        if self.is_game_active and not self._controller_is_human(self.game.current):
            self._schedule_engine_turn(80)


    def closeEvent(self, event):
        self._inspection_timer.stop()
        self._desired_inspection = None
        self._save_layout()
        self._layout_timer.stop()
        self._save_session(clean=True)
        self._session_timer.stop()
        self._closing = True
        self._invalidate_match_callbacks()
        self._series_enabled = False
        self._clock_timer.stop()
        self._autosave_current_game(final=True)
        if hasattr(self, "engine_controller"):
            self._engine_mode = "idle"
            # Disconnect callbacks before QObject/Python teardown, even after bestmove.
            self.engine_controller.close()
        super().closeEvent(event)
