"""Standalone Edit Position window for Co Long Phuong."""

import os
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import Qt, QRectF, QPoint, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QMessageBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from engine.board import Board
from engine.game import Game
from engine.pieces import Piece, PieceType, Player, initial_facing
from engine.position_editor import (
    STANDARD_KINGS_PER_SIDE,
    STANDARD_TOTALS,
    clear_position,
    fill_hand,
    position_counts,
    position_has_overflow,
)
from gui.board_canvas import BoardCanvas, BOARD_COLS, BOARD_ROWS, COLOR_BOARD_BG
from gui.constants import BG, BORDER, DIR_ICONS, DIR_PIECES, PANEL, TEXT, TEXT_MUTED
from gui.toolbar import ActionToolbar
from gui.widgets import KomadaiWidget, StackInspectorWidget


PIECE_COLUMNS = [
    ("Vương", PieceType.VUONG, "vuong"),
    ("Long", PieceType.LONG, "long"),
    ("Phượng", PieceType.PHUONG, "phuong"),
    ("Tướng", PieceType.TUONG, "tuong"),
    ("Sĩ", PieceType.SI, "si"),
    ("Kỵ", PieceType.KI, "ky"),
    ("Xa", PieceType.XA, "xa"),
    ("Binh", PieceType.BINH, "binh"),
]


class EditorBoardCanvas(BoardCanvas):
    """BoardCanvas variant with unrestricted position-edit interactions."""

    positionChanged = pyqtSignal()
    editorSelectionChanged = pyqtSignal(object)

    def __init__(self, game_instance: Game, parent=None):
        super().__init__(game_instance, parent)
        self.setMinimumSize(390, 390)
        self.show_toolbar = False
        self.margin_top = 24
        self.margin_right = 24

        self.tool_mode: str = "move"  # move | delete | place
        self.palette_piece: Optional[Tuple[Player, PieceType]] = None
        self.hand_piece: Optional[Tuple[Player, PieceType]] = None
        self.team_mode: bool = False
        self._drag_src: Optional[Tuple[int, int]] = None
        self._hand_targets: Dict[Player, QWidget] = {}

        # Editing uses its own selection; normal move previews stay unused.
        self.pending_move = None
        self.selected_hand_piece = None

    def set_hand_drop_targets(self, cam_widget: QWidget, xanh_widget: QWidget):
        self._hand_targets = {
            Player.CAM: cam_widget,
            Player.XANH: xanh_widget,
        }

    def set_tool_mode(self, mode: str):
        self.tool_mode = mode
        if mode != "place":
            self.palette_piece = None
        if mode != "move":
            self.hand_piece = None
        self._drag_src = None
        self.update()

    def set_palette_piece(self, player: Player, ptype: PieceType):
        self.tool_mode = "place"
        self.palette_piece = (player, ptype)
        self.hand_piece = None
        self._drag_src = None
        self.update()

    def set_hand_piece(self, player: Player, ptype: PieceType):
        selected = (player, ptype)
        if self.tool_mode == "move" and self.hand_piece == selected:
            self.hand_piece = None
        else:
            self.tool_mode = "move"
            self.palette_piece = None
            self.hand_piece = selected
        self._drag_src = None
        self.update()

    def set_team_mode(self, enabled: bool):
        self.team_mode = bool(enabled)

    def clear_editor_selection(self):
        self.selected_cell = None
        self._drag_src = None
        self.editorSelectionChanged.emit(None)
        self.update()

    def _select_cell(self, cell: Optional[Tuple[int, int]]):
        self.selected_cell = cell
        self.editorSelectionChanged.emit(cell)
        self.update()

    def _notify_changed(self, select_cell: Optional[Tuple[int, int]] = None):
        if select_cell is not None:
            self._select_cell(select_cell)
        else:
            self.editorSelectionChanged.emit(self.selected_cell)
        self.positionChanged.emit()
        self.update()

    def _remove_one_from_hand(self, player: Player, ptype: PieceType) -> bool:
        board = self.game.board
        # Captured/custom hand pieces are consumed before pre-game reserve pieces.
        if ptype in board.prisoners[player]:
            board.prisoners[player].remove(ptype)
            return True
        if ptype in board.reserve[player]:
            board.reserve[player].remove(ptype)
            return True
        return False

    def hand_count(self, player: Player, ptype: PieceType) -> int:
        board = self.game.board
        return board.prisoners[player].count(ptype) + board.reserve[player].count(ptype)

    def rotate_selected(self, rot_dir: int):
        if self.selected_cell is None:
            return
        sq = self.game.board.sq(*self.selected_cell)
        if sq.is_empty or not sq.top.can_rotate():
            return
        sq.top.facing = (sq.top.facing + (1 if rot_dir > 0 else -1)) % 4
        self._notify_changed(self.selected_cell)

    def delete_stack_level(self, level: int):
        """Delete the selected inspector level (1 == top), only in delete mode."""
        if self.tool_mode != "delete" or self.selected_cell is None:
            return
        sq = self.game.board.sq(*self.selected_cell)
        if sq.is_empty or level < 1 or level > len(sq.stack):
            return
        idx = len(sq.stack) - level
        sq.stack.pop(idx)
        if sq.is_empty:
            self._select_cell(None)
        self._notify_changed(self.selected_cell)

    def _global_point_in_widget(self, point, widget: QWidget) -> bool:
        top_left = widget.mapToGlobal(QPoint(0, 0))
        local_x = point.x() - top_left.x()
        local_y = point.y() - top_left.y()
        return 0 <= local_x < widget.width() and 0 <= local_y < widget.height()

    def _move_board_to_hand(self, src: Tuple[int, int], player: Player) -> bool:
        sq = self.game.board.sq(*src)
        if sq.is_empty:
            return False
        moving = list(sq.stack) if self.team_mode else [sq.top]
        # Vương cannot be held on a komadai.
        if any(piece.ptype is PieceType.VUONG for piece in moving):
            return False

        if self.team_mode:
            sq.stack.clear()
        else:
            sq.stack.pop()
        self.game.board.prisoners[player].extend(piece.ptype for piece in moving)
        return True

    def _move_between_cells(self, src: Tuple[int, int], dst: Tuple[int, int]) -> bool:
        if src == dst:
            return False
        source = self.game.board.sq(*src)
        if source.is_empty:
            return False
        destination = self.game.board.sq(*dst)

        if self.team_mode:
            moving = list(source.stack)
            source.stack.clear()
        else:
            moving = [source.stack.pop()]
        destination.stack.extend(moving)
        return True

    def mousePressEvent(self, event):
        """Edit-board interaction uses click-select, click-destination semantics.

        No movement rule is consulted here.  The editor modifies stacks directly:
        Group OFF moves only the top piece; Group ON moves the whole stack.
        """
        if event.button() != Qt.MouseButton.LeftButton:
            return

        cell = self._pos_to_cell(event.position())
        if cell is None:
            return

        sq = self.game.board.sq(*cell)

        if self.tool_mode == "delete":
            if not sq.is_empty:
                sq.stack.pop()  # delete top first
                self._drag_src = None
                self._select_cell(cell if not sq.is_empty else None)
                self._notify_changed(self.selected_cell)
            return

        if self.tool_mode == "place" and self.palette_piece is not None:
            player, ptype = self.palette_piece
            sq.stack.append(Piece(ptype, player, initial_facing(player)))
            self._drag_src = None
            self._notify_changed(cell)
            return

        if self.tool_mode == "move" and self.hand_piece is not None:
            player, ptype = self.hand_piece
            if self._remove_one_from_hand(player, ptype):
                sq.stack.append(Piece(ptype, player, initial_facing(player)))
                if self.hand_count(player, ptype) <= 0:
                    self.hand_piece = None
                self._drag_src = None
                self._notify_changed(cell)
            return

        if self.tool_mode != "move":
            return

        # First click: choose any occupied source square.
        if self._drag_src is None:
            if not sq.is_empty:
                self._drag_src = cell
                self._select_cell(cell)
            return

        # Second click: move freely to any board square, regardless of rules.
        src = self._drag_src
        if cell == src:
            # Clicking the selected source again cancels the move selection.
            self._drag_src = None
            self._select_cell(None)
            return

        if self._move_between_cells(src, cell):
            self._drag_src = None
            self._notify_changed(cell)
        else:
            self._drag_src = None
            self._select_cell(None)

    def mouseReleaseEvent(self, event):
        """Movement is intentionally click-based in Edit Position, not drag-based."""
        event.accept()

    def paintEvent(self, event):
        """Lean editor paint path: no legal-move generation during repaint."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bx, by = self.board_rect.x(), self.board_rect.y()
        bw = self.board_rect.width()
        cs = self.cell_size
        painter.fillRect(self.board_rect, COLOR_BOARD_BG)

        def cell_rect(r: int, c: int) -> QRectF:
            sr, sc = self._to_screen_coords(r, c)
            return QRectF(bx + sc * cs, by + sr * cs, cs, cs)

        if self.selected_cell is not None:
            painter.fillRect(cell_rect(*self.selected_cell), QColor("#b7f7b7"))

        painter.setPen(QPen(QColor("#414141"), 1))
        for i in range(10):
            painter.drawLine(int(bx + i * cs), int(by), int(bx + i * cs), int(by + bw))
            painter.drawLine(int(bx), int(by + i * cs), int(bx + bw), int(by + i * cs))
        painter.setPen(QPen(QColor("#1b0e03"), 2))
        painter.drawRect(self.board_rect)

        if self.show_coordinates:
            painter.setPen(QPen(QColor("#424242")))
            painter.setFont(QFont("Segoe UI", max(8, int(cs * 0.22)), QFont.Weight.Bold))
            cols = list(reversed(BOARD_COLS)) if self.is_flipped else BOARD_COLS
            rows = list(reversed(BOARD_ROWS)) if self.is_flipped else BOARD_ROWS
            for c, lbl in enumerate(cols):
                painter.drawText(
                    QRectF(bx + c * cs, by - self.margin_top, cs, self.margin_top),
                    Qt.AlignmentFlag.AlignCenter,
                    lbl,
                )
            for r, lbl in enumerate(rows):
                painter.drawText(
                    QRectF(bx + bw + 4, by + r * cs, self.margin_right - 4, cs),
                    Qt.AlignmentFlag.AlignCenter,
                    lbl,
                )

        piece_size = cs * 0.88
        for r in range(9):
            for c in range(9):
                sq = self.game.board.sq(r, c)
                if sq.is_empty:
                    continue
                sr, sc = self._to_screen_coords(r, c)
                self._draw_piece(
                    painter,
                    sq.top,
                    bx + (sc + 0.5) * cs,
                    by + (sr + 0.5) * cs,
                    piece_size,
                    stack_len=len(sq.stack),
                    opacity=1.0,
                )


class EditPositionDialog(QDialog):
    """Modal position editor that returns a new Game root/base position."""

    def __init__(self, initial_board: Board, current_player: Player, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Position - ColongphuongGUI")
        # QDialog normally exposes only Close on Windows.  Edit Position behaves
        # like a regular application window, so keep the native Minimize /
        # Maximize / Close controls and normal title-bar maximize behavior.
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        # Fit the editor inside the current desktop work area.  The previous
        # fixed 1220x820 layout was taller than many laptop screens/taskbars.
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_w = min(1220, max(900, available.width() - 32))
            target_h = min(760, max(600, available.height() - 32))
        else:
            target_w, target_h = 1180, 700
        self.resize(target_w, target_h)
        self.setMinimumSize(min(900, target_w), min(600, target_h))
        self.setSizeGripEnabled(True)
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; color: {TEXT}; }}"
            f"QRadioButton {{ color: {TEXT}; }}"
        )

        self.editor_game = Game()
        self.editor_game.set_base_position(initial_board, current_player)
        self._result_board: Optional[Board] = None
        self._result_player: Player = current_player
        self._palette_buttons: Dict[Tuple[Player, PieceType], QToolButton] = {}
        self._count_labels: Dict[PieceType, QLabel] = {}

        self._build_ui(current_player)
        self._refresh_all()

    # --------------------------- UI construction ---------------------------
    def _make_top_button(self, text: str, handler, icon_file: str = "") -> QPushButton:
        """Compact command button used in the lower Edit Position control strip."""
        btn = QPushButton(text)
        btn.setMinimumHeight(32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_file:
            icon_path = os.path.join(DIR_ICONS, icon_file)
            if os.path.isfile(icon_path):
                btn.setIcon(QIcon(icon_path))
                btn.setIconSize(QSize(18, 18))
        btn.setStyleSheet(
            "QPushButton { background:#ffffff; color:#1f2937; border:1px solid #cbd5e1; "
            "padding:5px 10px; font-size:12px; font-weight:600; }"
            "QPushButton:hover { color:#0f6fa8; background:#eef6fc; border-color:#93c5fd; }"
            "QPushButton:disabled { color:#94a3b8; background:#f1f5f9; }"
        )
        btn.clicked.connect(handler)
        return btn

    def _build_ui(self, current_player: Player):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Main edit area.  Keep both Komadai physically attached to the board
        # instead of letting BoardCanvas stretch across the whole window.
        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(0)
        main_row.addStretch(1)

        center_group = QHBoxLayout()
        center_group.setContentsMargins(0, 0, 0, 0)
        center_group.setSpacing(8)

        # Upper-left Komadai host.
        self.left_hand_host = QVBoxLayout()
        self.left_hand_host.setContentsMargins(0, 0, 0, 0)
        self.left_hand_host.setSpacing(0)

        self.komadai_cam = KomadaiWidget(side="cam")
        self.komadai_xanh = KomadaiWidget(side="xanh")
        self.komadai_cam.pieceSelected.connect(self._on_hand_piece_selected)
        self.komadai_xanh.pieceSelected.connect(self._on_hand_piece_selected)

        self.left_hand_host.addWidget(self.komadai_cam, alignment=Qt.AlignmentFlag.AlignTop)
        self.left_hand_host.addStretch(1)
        center_group.addLayout(self.left_hand_host)

        # Existing action toolbar sits immediately next to the board.
        self.action_toolbar = ActionToolbar()
        self.action_toolbar.btn_tick.hide()
        self.action_toolbar.btn_resign.hide()
        self.action_toolbar.set_team_mode(False)
        self.action_toolbar.btn_group.setEnabled(True)
        self.action_toolbar.rotateClicked.connect(self._rotate_selected)
        self.action_toolbar.groupStateChanged.connect(self._on_group_mode)
        center_group.addWidget(self.action_toolbar, alignment=Qt.AlignmentFlag.AlignTop)

        # The editor board has a bounded width.  It may grow vertically with the
        # window, but it no longer consumes all spare horizontal space.
        self.board_canvas = EditorBoardCanvas(self.editor_game)
        self.board_canvas.positionChanged.connect(self._refresh_all)
        self.board_canvas.editorSelectionChanged.connect(self._on_editor_selection)
        self.board_canvas.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.board_canvas.setFixedWidth(500)
        center_group.addWidget(self.board_canvas)

        # Lower-right Komadai host, directly beside the board.
        self.right_hand_host = QVBoxLayout()
        self.right_hand_host.setContentsMargins(0, 0, 0, 0)
        self.right_hand_host.setSpacing(0)
        self.right_hand_host.addStretch(1)
        self.right_hand_host.addWidget(self.komadai_xanh, alignment=Qt.AlignmentFlag.AlignBottom)
        center_group.addLayout(self.right_hand_host)

        main_row.addLayout(center_group)
        main_row.addStretch(1)
        root.addLayout(main_row, 1)

        self.board_canvas.set_hand_drop_targets(self.komadai_cam, self.komadai_xanh)

        # Stack inspector is deliberately outside the right Komadai column so
        # its 300-340 px width can never push Xanh away from the board.
        self.stack_inspector = StackInspectorWidget()
        self.stack_inspector.pieceClicked.connect(self.board_canvas.delete_stack_level)
        inspector_row = QHBoxLayout()
        inspector_row.setContentsMargins(0, 0, 0, 0)
        inspector_row.addStretch(1)
        inspector_row.addWidget(self.stack_inspector)
        inspector_row.addStretch(1)
        root.addLayout(inspector_row)

        # Lower control/palette panel.
        palette_frame = QFrame()
        palette_frame.setStyleSheet(
            f"QFrame {{ background:{PANEL}; border:1px solid {BORDER}; }}"
        )
        palette_outer = QVBoxLayout(palette_frame)
        palette_outer.setContentsMargins(8, 5, 8, 5)
        palette_outer.setSpacing(4)

        command_row = QHBoxLayout()
        command_row.setSpacing(6)
        self.btn_start = self._make_top_button("Start position", self._starting_position, "start.svg")
        self.btn_clear = self._make_top_button("Clear board", self._clear_board, "bin.svg")
        self.btn_fill_xanh = self._make_top_button("Fill hand of Xanh", lambda: self._fill_hand(Player.XANH))
        self.btn_fill_cam = self._make_top_button("Fill hand of Cam", lambda: self._fill_hand(Player.CAM))
        self.btn_flip = self._make_top_button("Turn board", self._turn_board)
        for btn in (self.btn_start, self.btn_clear, self.btn_fill_xanh, self.btn_fill_cam, self.btn_flip):
            command_row.addWidget(btn, 1)
        palette_outer.addLayout(command_row)

        palette_row = QHBoxLayout()
        palette_row.setSpacing(6)
        pieces_area = QHBoxLayout()
        pieces_area.setSpacing(5)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)

        for col, (label, ptype, asset_name) in enumerate(PIECE_COLUMNS):
            cell = QVBoxLayout()
            cell.setSpacing(1)
            for player, side in ((Player.CAM, "cam"), (Player.XANH, "xanh")):
                btn = QToolButton()
                btn.setCheckable(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                # Smaller, borderless palette pieces: the SVG itself is the visual.
                btn.setFixedSize(54, 42)
                path = os.path.join(DIR_PIECES, f"{side}_{asset_name}.svg")
                if os.path.isfile(path):
                    btn.setIcon(QIcon(path))
                    btn.setIconSize(QSize(38, 38))
                else:
                    btn.setText(f"{side[:1].upper()} {label}")
                btn.setToolTip(f"{label} - {'Cam' if player is Player.CAM else 'Xanh'}")
                btn.setStyleSheet(
                    "QToolButton { background:transparent; border:none; padding:1px; }"
                    "QToolButton:hover { background:#f1f5f9; }"
                    "QToolButton:checked { background:#eaf5fc; border-bottom:2px solid #1683c5; }"
                )
                btn.clicked.connect(lambda checked, pl=player, pt=ptype: self._select_palette(pl, pt))
                self.tool_group.addButton(btn)
                self._palette_buttons[(player, ptype)] = btn
                cell.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

            count = QLabel()
            count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count.setStyleSheet("border:none; font-size:11px; color:#111827;")
            self._count_labels[ptype] = count
            cell.addWidget(count)
            pieces_area.addLayout(cell)

        palette_row.addLayout(pieces_area, 1)

        tool_col = QVBoxLayout()
        tool_col.setSpacing(4)
        self.btn_delete_tool = QToolButton()
        self.btn_delete_tool.setToolTip("Xóa từng quân (quân trên cùng trước)")
        self.btn_delete_tool.setCheckable(True)
        self.btn_delete_tool.setFixedSize(48, 48)
        bin_path = os.path.join(DIR_ICONS, "bin.svg")
        if os.path.isfile(bin_path):
            self.btn_delete_tool.setIcon(QIcon(bin_path))
            self.btn_delete_tool.setIconSize(QSize(34, 34))
        else:
            self.btn_delete_tool.setText("X")
        self.btn_delete_tool.setStyleSheet(
            "QToolButton { background:#f8fafc; border:1px solid #d1d5db; }"
            "QToolButton:checked { border:2px solid #ef4444; background:#fef2f2; }"
        )
        self.btn_delete_tool.clicked.connect(lambda: self._select_tool("delete"))
        self.tool_group.addButton(self.btn_delete_tool)
        tool_col.addWidget(self.btn_delete_tool)

        self.btn_move_tool = QToolButton()
        self.btn_move_tool.setToolTip("Di chuyển quân / đội")
        self.btn_move_tool.setCheckable(True)
        self.btn_move_tool.setChecked(True)
        self.btn_move_tool.setFixedSize(48, 48)
        # Prefer a dedicated hand.svg when supplied.  Until then, use the
        # requested bin.svg fallback so all editor icons come from assets/icons.
        hand_path = os.path.join(DIR_ICONS, "hand.svg")
        if not os.path.isfile(hand_path):
            hand_path = bin_path
        if os.path.isfile(hand_path):
            self.btn_move_tool.setIcon(QIcon(hand_path))
            self.btn_move_tool.setIconSize(QSize(34, 34))
        else:
            self.btn_move_tool.setText("M")
        self.btn_move_tool.setStyleSheet(
            "QToolButton { background:#f8fafc; border:1px solid #d1d5db; }"
            "QToolButton:checked { border:2px solid #65a30d; background:#f7fee7; }"
        )
        self.btn_move_tool.clicked.connect(lambda: self._select_tool("move"))
        self.tool_group.addButton(self.btn_move_tool)
        tool_col.addWidget(self.btn_move_tool)
        tool_col.addStretch(1)
        palette_row.addLayout(tool_col)
        palette_outer.addLayout(palette_row)
        root.addWidget(palette_frame)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(QLabel("Lượt đi:"))
        self.radio_cam = QRadioButton("Cam")
        self.radio_xanh = QRadioButton("Xanh")
        self.radio_cam.setChecked(current_player is Player.CAM)
        self.radio_xanh.setChecked(current_player is Player.XANH)
        bottom.addWidget(self.radio_cam)
        bottom.addWidget(self.radio_xanh)
        bottom.addStretch(1)

        self.btn_apply = QPushButton("Áp dụng")
        self.btn_cancel = QPushButton("Hủy")
        self.btn_apply.setMinimumSize(100, 34)
        self.btn_cancel.setMinimumSize(90, 34)
        self.btn_apply.setStyleSheet(
            "QPushButton { background:#1683c5; color:white; border:none; font-weight:700; }"
            "QPushButton:hover { background:#0f6fa8; }"
        )
        self.btn_cancel.setStyleSheet(
            "QPushButton { background:white; color:#334155; border:1px solid #cbd5e1; }"
        )
        self.btn_apply.clicked.connect(self._apply)
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_apply)
        root.addLayout(bottom)

        self._select_tool("move")

    # ------------------------------- Actions -------------------------------
    def _starting_position(self):
        board = Board()
        board.setup_initial()
        self.editor_game.board = board
        self.radio_cam.setChecked(True)
        self.board_canvas.clear_editor_selection()
        self._refresh_all()

    def _clear_board(self):
        clear_position(self.editor_game.board)
        self.board_canvas.clear_editor_selection()
        self._refresh_all()

    def _fill_hand(self, player: Player):
        fill_hand(self.editor_game.board, player)
        self._refresh_all()

    def _turn_board(self):
        self.board_canvas.toggle_flip()
        flipped = self.board_canvas.is_flipped
        self.komadai_cam.set_flipped(flipped)
        self.komadai_xanh.set_flipped(flipped)
        self._arrange_hands(flipped)
        self._refresh_inspector()

    def _arrange_hands(self, flipped: bool):
        """Mirror the main View layout: upper-left side, lower-right opponent."""
        self.left_hand_host.removeWidget(self.komadai_cam)
        self.left_hand_host.removeWidget(self.komadai_xanh)
        self.right_hand_host.removeWidget(self.komadai_cam)
        self.right_hand_host.removeWidget(self.komadai_xanh)

        if flipped:
            # Flipped board: Xanh upper-left, Cam lower-right.
            self.left_hand_host.insertWidget(0, self.komadai_xanh, alignment=Qt.AlignmentFlag.AlignTop)
            self.right_hand_host.addWidget(self.komadai_cam, alignment=Qt.AlignmentFlag.AlignBottom)
        else:
            # Normal board: Cam upper-left, Xanh lower-right.
            self.left_hand_host.insertWidget(0, self.komadai_cam, alignment=Qt.AlignmentFlag.AlignTop)
            self.right_hand_host.addWidget(self.komadai_xanh, alignment=Qt.AlignmentFlag.AlignBottom)

    def _select_palette(self, player: Player, ptype: PieceType):
        self.board_canvas.set_palette_piece(player, ptype)
        self.komadai_cam.clear_selection()
        self.komadai_xanh.clear_selection()

    def _select_tool(self, mode: str):
        self.board_canvas.set_tool_mode(mode)
        if mode == "move":
            self.btn_move_tool.setChecked(True)
        elif mode == "delete":
            self.btn_delete_tool.setChecked(True)
        self.komadai_cam.clear_selection()
        self.komadai_xanh.clear_selection()

    def _on_hand_piece_selected(self, side: str, ptype: PieceType):
        player = Player.CAM if side == "cam" else Player.XANH
        if self.board_canvas.hand_count(player, ptype) <= 0:
            return
        self.btn_move_tool.setChecked(True)
        self.board_canvas.set_hand_piece(player, ptype)

    def _on_group_mode(self, enabled: bool):
        self.board_canvas.set_team_mode(enabled)
        self.action_toolbar.btn_group.setEnabled(True)

    def _rotate_selected(self, rot_dir: int):
        self.board_canvas.rotate_selected(rot_dir)

    def _on_editor_selection(self, cell):
        self._refresh_inspector(cell)
        can_rotate = False
        if cell is not None:
            sq = self.editor_game.board.sq(*cell)
            can_rotate = not sq.is_empty and sq.top.can_rotate()
        self.action_toolbar.set_piece_selected_state(
            selected=cell is not None,
            can_team=True,
            can_tick=False,
            can_rotate=can_rotate,
        )
        # Group mode is a persistent editor setting, not selection-dependent.
        self.action_toolbar.btn_group.setEnabled(True)

    def _refresh_inspector(self, cell=None):
        if cell is None:
            cell = self.board_canvas.selected_cell
        if cell is None:
            self.stack_inspector.clear()
            return
        sq = self.editor_game.board.sq(*cell)
        rows, cols = "abcdefghi", "987654321"
        coord = f"{rows[cell[0]]}{cols[cell[1]]}"
        self.stack_inspector.set_stack(
            list(sq.stack),
            is_flipped=self.board_canvas.is_flipped,
            coord_name=coord,
        )

    def _refresh_counts(self):
        totals, kings = position_counts(self.editor_game.board)

        cam_now = kings[Player.CAM]
        xanh_now = kings[Player.XANH]
        cam_color = "#dc2626" if cam_now > STANDARD_KINGS_PER_SIDE else "#111827"
        xanh_color = "#dc2626" if xanh_now > STANDARD_KINGS_PER_SIDE else "#111827"
        self._count_labels[PieceType.VUONG].setText(
            f"Vương cam: <span style='color:{cam_color}'>{cam_now}</span>/1<br>"
            f"Vương xanh: <span style='color:{xanh_color}'>{xanh_now}</span>/1"
        )

        for label, ptype, _ in PIECE_COLUMNS[1:]:
            current = totals[ptype]
            maximum = STANDARD_TOTALS[ptype]
            color = "#dc2626" if current > maximum else "#111827"
            self._count_labels[ptype].setText(
                f"{label}: <span style='color:{color}'>{current}</span>/{maximum}"
            )

        overflow = position_has_overflow(self.editor_game.board)
        self.btn_fill_cam.setEnabled(not overflow)
        self.btn_fill_xanh.setEnabled(not overflow)
        tooltip = "Vị trí đang vượt tổng số quân chuẩn; Fill Hand bị khóa." if overflow else ""
        self.btn_fill_cam.setToolTip(tooltip)
        self.btn_fill_xanh.setToolTip(tooltip)

    def _refresh_all(self):
        self.komadai_cam.update_counts(self.editor_game.board, Player.CAM)
        self.komadai_xanh.update_counts(self.editor_game.board, Player.XANH)
        self._refresh_counts()
        self._refresh_inspector()
        self._on_editor_selection(self.board_canvas.selected_cell)

        hp = self.board_canvas.hand_piece
        if hp is not None and self.board_canvas.hand_count(*hp) <= 0:
            self.board_canvas.hand_piece = None
            self.komadai_cam.clear_selection()
            self.komadai_xanh.clear_selection()
        self.board_canvas.update()

    def _apply(self):
        player = Player.CAM if self.radio_cam.isChecked() else Player.XANH
        if position_has_overflow(self.editor_game.board):
            QMessageBox.warning(self, 'Invalid position',
                                'Tổng số quân vượt quá số lượng chuẩn.')
            return
        counts, kings = position_counts(self.editor_game.board)
        if any(kings[side] != 1 for side in Player):
            QMessageBox.warning(self, 'Invalid position',
                                'Cần đúng một Vương CAM và một Vương XANH.')
            return
        for row in self.editor_game.board.grid:
            for cell in row:
                if len(cell.stack) > 38 or (cell.stack and
                        (any(piece.owner is not cell.top.owner for piece in cell.stack)
                         or (len(cell.stack) > 1 and
                             any(piece.ptype is PieceType.VUONG for piece in cell.stack)))):
                    QMessageBox.warning(self, 'Invalid position',
                                        'Stack không hợp lệ (phe, Vương hoặc quá 38 quân).')
                    return
        self._result_board = self.editor_game.board.clone()
        self._result_player = Player.CAM if self.radio_cam.isChecked() else Player.XANH
        self.accept()

    def result_position(self) -> Tuple[Board, Player]:
        if self._result_board is None:
            raise RuntimeError("Edit Position has not been applied")
        return self._result_board.clone(), self._result_player
