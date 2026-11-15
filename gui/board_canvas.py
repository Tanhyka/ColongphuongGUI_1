"""Interactive board canvas widget for Co Long Phuong."""

import math
import os
from typing import Optional, Tuple, Set, List
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPixmap, QPolygonF

from engine.game import Game
from engine.pieces import Piece, Player, PieceType, NON_ROTATABLE, initial_facing
from engine.rules import Move
from gui.constants import DIR_PIECES
from gui.helpers import SvgHelper
from gui.toolbar import ActionToolbar

BOARD_COLS = ['9', '8', '7', '6', '5', '4', '3', '2', '1']
BOARD_ROWS = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']

COLOR_BOARD_BG = QColor("#ffffff")
COLOR_LAST_MOVE = QColor("#ff6b6b")
COLOR_SELECTED = QColor("#00e600")
COLOR_SELECTED_OPPONENT = QColor("#ffb3b3")
COLOR_POSSIBLE = QColor("#98ec98")

# Annotation colors (chess.com / lichess style)
COLOR_ANNOT_GREEN = QColor(52, 168, 83, 205)   # lishogi-like annotation green
COLOR_ANNOT_GREEN_FILL = QColor(52, 168, 83, 115)


class BoardCanvas(QWidget):
    moveMade = pyqtSignal(object)
    engineArrowsChanged = pyqtSignal()
    pieceSelected = pyqtSignal(bool)
    selectionStateChanged = pyqtSignal(bool, bool, bool)
    geometryUpdated = pyqtSignal()
    cellInspected = pyqtSignal(object, object)

    def __init__(self, game_instance: Game, parent=None):
        super().__init__(parent)
        self.game = game_instance
        self.setMinimumSize(240, 240)

        self.selected_cell: Optional[Tuple[int, int]] = None
        self.pending_move: Optional[Move] = None
        self.selected_hand_piece: Optional[PieceType] = None
        self.last_move: Optional[Move] = None

        self.toolbar: Optional[ActionToolbar] = None
        self.show_toolbar: bool = True
        self.show_coordinates: bool = True
        self.is_team_mode: bool = True
        self.is_flipped: bool = False
        self.moves_enabled: bool = True
        self.allow_analysis_after_result: bool = True

        self.cell_size: float = 60.0
        self.board_rect: QRectF = QRectF(0, 0, 0, 0)
        self.margin_top: int = 24
        self.margin_right: int = 24

        # --- Right-click annotations (arrows + circles) ---
        # circles: Set[(r, c)]
        # arrows: Set[((r1,c1), (r2,c2))]
        self.annot_circles: Set[Tuple[int, int]] = set()
        self.annot_arrows: Set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
        self._annot_drag_start: Optional[Tuple[int, int]] = None   # cell where right-drag began
        self._annot_drag_current: Optional[Tuple[int, int]] = None  # cell currently hovered during drag
        self._annot_dragging_ctrl: bool = False  # True if this drag started as Ctrl+Left instead of Right

        # --- Dynamic MultiPV Engine Arrows ---
        self.engine_arrows: dict = {}
        self.show_engine_arrows: bool = True
        self.max_engine_arrows: int = 1

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def _is_position_blocked(self) -> bool:
        if self.allow_analysis_after_result and hasattr(self.game, "is_board_terminal"):
            return self.game.is_board_terminal()
        return self.game.is_over()

    def _legal_moves(self):
        return self.game.legal_moves(allow_nonterminal_analysis=self.allow_analysis_after_result)

    def _commit_move(self, move: Move) -> bool:
        return self.game.make_move(move, allow_nonterminal_analysis=self.allow_analysis_after_result)

    def toggle_flip(self):
        self.is_flipped = not self.is_flipped
        self.update()

    def set_moves_enabled(self, enabled: bool):
        """Enables/disables move input while keeping annotations available."""
        self.moves_enabled = bool(enabled)
        if not self.moves_enabled:
            self.reset_transient_state(clear_last_move=False)

    def reset_transient_state(self, clear_last_move: bool = True):
        """Clears selections/previews that must not leak across New/Open/Stop."""
        self.selected_cell = None
        self.pending_move = None
        self.selected_hand_piece = None
        if clear_last_move:
            self.last_move = None
        self.pieceSelected.emit(False)
        self.cellInspected.emit(None, [])
        self._sync_toolbar_state()
        self.update()

    def set_engine_arrow(self, rank: int, arrow_data: Optional[dict]):
        """Sets or clears an engine arrow for a MultiPV rank (1, 2, or 3)."""
        if arrow_data is None:
            self.engine_arrows.pop(rank, None)
        else:
            if rank <= self.max_engine_arrows:
                self.engine_arrows[rank] = dict(arrow_data)
        for rk in list(self.engine_arrows.keys()):
            if rk > self.max_engine_arrows:
                self.engine_arrows.pop(rk, None)
        self.update()
        self.engineArrowsChanged.emit()

    def clear_engine_arrows(self):
        """Clears all dynamic MultiPV engine arrows from the board."""
        if self.engine_arrows:
            self.engine_arrows.clear()
            self.update()
            self.engineArrowsChanged.emit()

    def set_show_engine_arrows(self, show: bool):
        """Toggles visibility of dynamic MultiPV engine arrows."""
        self.show_engine_arrows = bool(show)
        self.update()
        self.engineArrowsChanged.emit()

    def set_max_engine_arrows(self, count: int):
        """Sets the maximum number of MultiPV arrows to display (1 to 3)."""
        self.max_engine_arrows = max(1, min(3, int(count)))
        for rk in list(self.engine_arrows.keys()):
            if rk > self.max_engine_arrows:
                self.engine_arrows.pop(rk, None)
        self.update()
        self.engineArrowsChanged.emit()

    def set_show_coordinates(self, visible: bool):
        """Bật / tắt hiển thị nhãn tọa độ a-i, 1-9."""
        self.show_coordinates = bool(visible)
        self.margin_top = 24 if self.show_coordinates else 8
        self.margin_right = 24 if self.show_coordinates else 8
        self._update_geometry()
        self.update()

    def set_toolbar_visible(self, visible: bool):
        """Bật / tắt hiển thị thanh công cụ ActionToolbar."""
        self.show_toolbar = bool(visible)
        if self.toolbar:
            self.toolbar.setVisible(self.show_toolbar)
        self._update_geometry()
        self.update()

    def _to_screen_coords(self, r: int, c: int) -> Tuple[int, int]:
        return (8 - r, 8 - c) if self.is_flipped else (r, c)

    def _to_matrix_coords(self, dr: int, dc: int) -> Tuple[int, int]:
        return (8 - dr, 8 - dc) if self.is_flipped else (dr, dc)

    def set_toolbar(self, toolbar: ActionToolbar):
        self.toolbar = toolbar
        self.toolbar.setParent(self)
        self.toolbar.setVisible(self.show_toolbar)

        self.toolbar.rotateClicked.connect(self._on_rotate_action)
        self.toolbar.tickClicked.connect(self._on_tick_action)
        self.toolbar.groupStateChanged.connect(self._on_group_mode_changed)

        self._sync_toolbar_position()
        self._sync_toolbar_state()
        self.geometryUpdated.emit()

    def _on_group_mode_changed(self, is_team_mode: bool):
        self.is_team_mode = bool(is_team_mode)
        self._sync_toolbar_state()
        self.update()

    def _sync_toolbar_state(self):
        if not self.toolbar:
            return

        selected = self.selected_cell is not None or self.pending_move is not None
        can_team = False
        can_rotate = False
        can_act = self.moves_enabled and not self._is_position_blocked()

        if can_act and self.pending_move is not None:
            can_rotate = self.pending_move.ptype not in NON_ROTATABLE
        elif can_act and self.selected_cell is not None:
            sq = self.game.board.sq(*self.selected_cell)
            if not sq.is_empty and sq.top.owner is self.game.current:
                can_rotate = sq.top.can_rotate()
                can_team = len(sq.stack) > 1

        self.toolbar.set_piece_selected_state(
            selected,
            can_team=can_team,
            can_tick=can_act and (self.pending_move is not None),
            can_rotate=can_rotate,
        )

    def _set_selection(self, cell: Optional[Tuple[int, int]]):
        self.selected_cell = cell
        self.pieceSelected.emit(cell is not None)
        self._sync_toolbar_state()

        if cell is not None:
            sq = self.game.board.sq(*cell)
            self.cellInspected.emit(cell, list(sq.stack))
        else:
            self.cellInspected.emit(None, [])

        self.update()

    def _cancel_pending(self):
        self.pending_move = None
        self._sync_toolbar_state()
        self.update()

    def select_hand_piece(self, ptype: PieceType):
        if not self.moves_enabled or self._is_position_blocked():
            return
        if self.selected_hand_piece == ptype:
            self.selected_hand_piece = None
        else:
            self.selected_hand_piece = ptype
            self._set_selection(None)
            self._cancel_pending()
        self.update()

    # ------------------------------------------------------------------
    # Rotation rules:
    # - Thả quân: có thể tiếp tục xoay tự do rồi mới bấm tick để xác nhận.
    # - Quân đã ở trên bàn: chỉ được xoay trái/phải 90 độ, và khi bấm nút
    #   xoay thì nước đi phải kết thúc ngay, không chờ tick xác nhận.
    # ------------------------------------------------------------------
    def _on_rotate_action(self, rot_dir: int):
        if not self.moves_enabled or self._is_position_blocked():
            return

        rot_dir = 1 if rot_dir > 0 else 3

        if self.pending_move is not None:
            if self.pending_move.ptype in NON_ROTATABLE:
                return

            if self.pending_move.kind == 'drop':
                self.pending_move.facing = ((self.pending_move.facing or 0) + rot_dir) % 4
                self.update()
                return

            committed = Move(
                kind=self.pending_move.kind,
                src=self.pending_move.src,
                dst=self.pending_move.dst,
                ptype=self.pending_move.ptype,
                facing=self.pending_move.facing,
                rotate_after=rot_dir,
            )
            if self._commit_move(committed):
                self.last_move = committed
                self._cancel_pending()
                self._set_selection(None)
                self._clear_annotations()
                self.moveMade.emit(committed)
                self.update()
            return

        if self.selected_cell is not None:
            sq = self.game.board.sq(*self.selected_cell)
            if not sq.is_empty and sq.top.owner is self.game.current and sq.top.can_rotate():
                committed = Move(
                    kind='rotate',
                    src=self.selected_cell,
                    ptype=sq.top.ptype,
                    rotate_after=rot_dir,
                )
                if self._commit_move(committed):
                    self.last_move = committed
                    self._set_selection(None)
                    self._clear_annotations()
                    self.moveMade.emit(committed)
                    self.update()

    def _on_tick_action(self):
        if not self.moves_enabled or self._is_position_blocked() or self.pending_move is None:
            return

        p = self.pending_move
        committed = Move(
            kind=p.kind,
            src=p.src,
            dst=p.dst,
            ptype=p.ptype,
            facing=p.facing,
            rotate_after=p.rotate_after,
        )
        if self._commit_move(committed):
            self.last_move = committed
            self._cancel_pending()
            self._set_selection(None)
            self._clear_annotations()
            self.moveMade.emit(committed)
            self.update()

    @staticmethod
    def toolbar_margin_for_cell(cell_size: float) -> int:
        """Reserve exactly enough space for the scaled buttons plus a gap."""
        button = ActionToolbar.button_dimension(cell_size)
        gap = ActionToolbar.board_gap(cell_size)
        return button + gap + 6

    def _sync_toolbar_position(self):
        if self.toolbar and self.board_rect.width() > 0 and self.show_toolbar:
            self.toolbar.update_scale(self.cell_size)
            gap = ActionToolbar.board_gap(self.cell_size)
            tb_x = int(self.board_rect.x() - self.toolbar.width() - gap)
            tb_y = int(self.board_rect.y())
            self.toolbar.move(max(0, tb_x), tb_y)
            self.toolbar.raise_()

    def _update_geometry(self):
        w, h = self.width(), self.height()
        # The toolbar slot is sized from the same cell size as its buttons.
        # Guess using the height first; the final grid may be width-limited.
        candidate_cell = max(1.0, (h - self.margin_top - 8) / 9.0)
        margin_left = self.toolbar_margin_for_cell(candidate_cell) if self.show_toolbar else 16
        avail_w = max(100, w - self.margin_right - margin_left - 8)
        avail_h = max(100, h - self.margin_top - 8)
        grid_pixel_size = min(avail_w, avail_h)
        self.cell_size = grid_pixel_size / 9.0

        offset_x = (w - (grid_pixel_size + self.margin_right + margin_left)) / 2 + margin_left
        offset_y = (h - (grid_pixel_size + self.margin_top)) / 2 + self.margin_top
        self.board_rect = QRectF(offset_x, offset_y, grid_pixel_size, grid_pixel_size)

        self._sync_toolbar_position()
        self.geometryUpdated.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_geometry()

    # ------------------------------------------------------------------
    # Annotation helpers
    # ------------------------------------------------------------------
    def _clear_annotations(self):
        self.annot_circles.clear()
        self.annot_arrows.clear()
        self._annot_drag_start = None
        self._annot_drag_current = None
        self.update()

    def _cell_center(self, r: int, c: int) -> QPointF:
        sr, sc = self._to_screen_coords(r, c)
        bx, by = self.board_rect.x(), self.board_rect.y()
        cs = self.cell_size
        return QPointF(bx + (sc + 0.5) * cs, by + (sr + 0.5) * cs)

    def _pos_to_cell(self, pos) -> Optional[Tuple[int, int]]:
        bx, by = self.board_rect.x(), self.board_rect.y()
        cs = self.cell_size
        if not self.board_rect.contains(pos):
            return None
        display_c = max(0, min(8, int((pos.x() - bx) // cs)))
        display_r = max(0, min(8, int((pos.y() - by) // cs)))
        return self._to_matrix_coords(display_r, display_c)

    def _draw_annotations(self, painter: QPainter):
        cs = self.cell_size

        # committed circles
        for (r, c) in self.annot_circles:
            center = self._cell_center(r, c)
            radius = cs * 0.42
            pen = QPen(COLOR_ANNOT_GREEN, max(2.0, cs * 0.06))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)

        # committed arrows
        for (src, dst) in self.annot_arrows:
            self._draw_arrow(painter, src, dst, COLOR_ANNOT_GREEN)

        # in-progress drag preview (arrow or circle, same pastel green,
        # slightly transparent to indicate it's not committed yet)
        if self._annot_drag_start is not None and self._annot_drag_current is not None:
            start, cur = self._annot_drag_start, self._annot_drag_current
            preview_color = QColor(COLOR_ANNOT_GREEN)
            preview_color.setAlpha(140)
            if start == cur:
                center = self._cell_center(*start)
                radius = cs * 0.42
                painter.setPen(QPen(preview_color, max(2.0, cs * 0.06)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, radius, radius)
            else:
                self._draw_arrow(painter, start, cur, preview_color)

    def _draw_arrow(self, painter: QPainter, src: Tuple[int, int], dst: Tuple[int, int], color: QColor):
        """Draw a single continuous lishogi-style filled arrow."""
        cs = self.cell_size
        p1 = self._cell_center(*src)
        p2 = self._cell_center(*dst)

        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = max(1e-6, (dx ** 2 + dy ** 2) ** 0.5)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux

        shaft_half = max(3.5, cs * 0.085)
        head_half = cs * 0.21
        head_len = cs * 0.34

        # Tip sits inside the target cell, similar to lishogi.
        tip = QPointF(p2.x() - ux * cs * 0.12, p2.y() - uy * cs * 0.12)
        base = QPointF(tip.x() - ux * head_len, tip.y() - uy * head_len)

        start_l = QPointF(p1.x() + px * shaft_half, p1.y() + py * shaft_half)
        start_r = QPointF(p1.x() - px * shaft_half, p1.y() - py * shaft_half)
        neck_l = QPointF(base.x() + px * shaft_half, base.y() + py * shaft_half)
        neck_r = QPointF(base.x() - px * shaft_half, base.y() - py * shaft_half)
        head_l = QPointF(base.x() + px * head_half, base.y() + py * head_half)
        head_r = QPointF(base.x() - px * head_half, base.y() - py * head_half)

        arrow = QPolygonF([start_l, neck_l, head_l, tip, head_r, neck_r, start_r])

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPolygon(arrow)
        # Rounded tail, while the head and shaft remain one continuous filled shape.
        painter.drawEllipse(p1, shaft_half, shaft_half)
        painter.restore()

    def _draw_multipv_arrow(self, painter: QPainter, arrow: dict, offset_perp: float = 0.0):
        """Vẽ mũi tên phân tích động trực quan cho các phương án MultiPV từ Engine:
        - MultiPV 1 (Tối ưu nhất): Xanh lá cây đậm (#16A34A), alpha 210, nét liền width 6px, đầu tam giác length 16px angle 35°.
        - MultiPV 2: Xanh dương (#2563EB), alpha 180, nét liền width 4px, đầu tam giác length 12px angle 30°.
        - MultiPV 3: Cam hổ phách (#F59E0B), alpha 160, nét đứt width 3px, đầu tam giác length 10px angle 25°.
        """
        rank = arrow.get("multipv", 1)
        if rank not in (1, 2, 3):
            return

        specs = {
            1: {
                "color": QColor(22, 163, 74, 210),   # #16A34A, alpha 210
                "pen_style": Qt.PenStyle.SolidLine,
                "width": 6.0,
                "head_len": 16.0,
                "angle_deg": 35.0,
            },
            2: {
                "color": QColor(37, 99, 235, 180),   # #2563EB, alpha 180
                "pen_style": Qt.PenStyle.SolidLine,
                "width": 4.0,
                "head_len": 12.0,
                "angle_deg": 30.0,
            },
            3: {
                "color": QColor(245, 158, 11, 160),  # #F59E0B (Cam), alpha 160
                "pen_style": Qt.PenStyle.DashLine,
                "width": 3.0,
                "head_len": 10.0,
                "angle_deg": 25.0,
            },
        }
        spec = specs[rank]
        color = spec["color"]
        pen_style = spec["pen_style"]
        width = spec["width"]
        head_len = spec["head_len"]
        angle_rad = math.radians(spec["angle_deg"])

        src = arrow.get("src")
        dst = arrow.get("dst")
        if dst is None:
            return

        cs = self.cell_size
        p2_raw = self._cell_center(*dst)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if src is None:
            # Drop move (Thả quân từ tay vào ô dst)
            cam_moving = arrow.get("cam", True)
            dir_y = 1.0 if (cam_moving != self.is_flipped) else -1.0
            p1 = QPointF(p2_raw.x() + offset_perp, p2_raw.y() - dir_y * cs * 0.75)
            tip = QPointF(p2_raw.x() + offset_perp, p2_raw.y() - dir_y * cs * 0.12)

            dx, dy = tip.x() - p1.x(), tip.y() - p1.y()
            length = max(1e-6, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            px, py = -uy, ux

            base = QPointF(tip.x() - ux * head_len, tip.y() - uy * head_len)
            half_w = head_len * math.tan(angle_rad)
            head_l = QPointF(base.x() + px * half_w, base.y() + py * half_w)
            head_r = QPointF(base.x() - px * half_w, base.y() - py * half_w)

            pen = QPen(color, width, pen_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(p1, base)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(p1, width * 0.9, width * 0.9)

            arrow_head = QPolygonF([tip, head_l, head_r])
            painter.drawPolygon(arrow_head)

            target_pen = QPen(color, max(1.5, width * 0.4), Qt.PenStyle.DashLine)
            painter.setPen(target_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(p2_raw, cs * 0.38, cs * 0.38)

        elif src == dst:
            # Xoay tại chỗ (Rotate on same square)
            center = p2_raw
            radius = cs * 0.32
            pen = QPen(color, width, pen_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            painter.drawArc(arc_rect, int(45 * 16), int(270 * 16))

            end_angle = math.radians(45)
            tip = QPointF(center.x() + radius * math.cos(end_angle), center.y() - radius * math.sin(end_angle))
            tan_x, tan_y = math.sin(end_angle), math.cos(end_angle)
            ux, uy = tan_x, tan_y
            px, py = -uy, ux
            base = QPointF(tip.x() - ux * head_len, tip.y() - uy * head_len)
            half_w = head_len * math.tan(angle_rad)
            head_l = QPointF(base.x() + px * half_w, base.y() + py * half_w)
            head_r = QPointF(base.x() - px * half_w, base.y() - py * half_w)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(QPolygonF([tip, head_l, head_r]))

        else:
            # Nước đi thông thường từ src sang dst
            p1_raw = self._cell_center(*src)
            dx, dy = p2_raw.x() - p1_raw.x(), p2_raw.y() - p1_raw.y()
            length = max(1e-6, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            px, py = -uy, ux

            p1 = QPointF(p1_raw.x() + px * offset_perp, p1_raw.y() + py * offset_perp)
            p2 = QPointF(p2_raw.x() + px * offset_perp, p2_raw.y() + py * offset_perp)

            tip_offset = min(cs * 0.12, length * 0.1)
            tip = QPointF(p2.x() - ux * tip_offset, p2.y() - uy * tip_offset)

            base = QPointF(tip.x() - ux * head_len, tip.y() - uy * head_len)
            half_w = head_len * math.tan(angle_rad)
            head_l = QPointF(base.x() + px * half_w, base.y() + py * half_w)
            head_r = QPointF(base.x() - px * half_w, base.y() - py * half_w)

            pen = QPen(color, width, pen_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(p1, base)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(p1, width * 0.85, width * 0.85)

            arrow_head = QPolygonF([tip, head_l, head_r])
            painter.drawPolygon(arrow_head)

        painter.restore()

    def _draw_engine_arrows(self, painter: QPainter):
        if getattr(self, "_overlay_active", False):
            return
        if not self.show_engine_arrows or not self.engine_arrows:
            return
        active_ranks = [rk for rk in (1, 2, 3) if rk in self.engine_arrows and rk <= self.max_engine_arrows]
        if not active_ranks:
            return

        offsets = {1: 0.0, 2: 0.0, 3: 0.0}
        cs = self.cell_size
        shift = cs * 0.09
        if 1 in self.engine_arrows and 2 in self.engine_arrows:
            a1, a2 = self.engine_arrows[1], self.engine_arrows[2]
            if a1.get("src") == a2.get("src") and a1.get("dst") == a2.get("dst"):
                offsets[1] = -shift
                offsets[2] = shift
        if 1 in self.engine_arrows and 3 in self.engine_arrows:
            a1, a3 = self.engine_arrows[1], self.engine_arrows[3]
            if a1.get("src") == a3.get("src") and a1.get("dst") == a3.get("dst"):
                offsets[3] = shift * 2.0

        for rk in sorted(active_ranks, reverse=True):
            self._draw_multipv_arrow(painter, self.engine_arrows[rk], offset_perp=offsets.get(rk, 0.0))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bx, by = self.board_rect.x(), self.board_rect.y()
        bw = self.board_rect.width()
        cs = self.cell_size

        # 1. Nền bàn cờ
        painter.fillRect(self.board_rect, COLOR_BOARD_BG)

        # 2. Ô di chuyển hợp lệ
        active_last_move = self.last_move or (self.game.current_node.move if self.game.current_node else None)

        dest_moves: Set[Tuple[int, int]] = set()
        if self.moves_enabled and not self._is_position_blocked() and self.pending_move is None:
            legal_moves = self._legal_moves()
            if self.selected_cell:
                sq_sel = self.game.board.sq(*self.selected_cell)
                if not sq_sel.is_empty and sq_sel.top.owner == self.game.current:
                    wanted_kind = 'team' if self.is_team_mode else 'single'
                    matches = [
                        m.dst for m in legal_moves
                        if m.src == self.selected_cell and m.dst and m.kind == wanted_kind
                    ] or [
                        m.dst for m in legal_moves
                        if m.src == self.selected_cell and m.dst and m.kind == 'single'
                    ]
                    dest_moves = set(matches)
            elif self.selected_hand_piece is not None:
                dest_moves = {
                    m.dst for m in legal_moves
                    if m.kind == 'drop' and m.dst and m.ptype == self.selected_hand_piece
                }

        def get_cell_rect(r: int, c: int) -> QRectF:
            sr, sc = self._to_screen_coords(r, c)
            return QRectF(bx + sc * cs, by + sr * cs, cs, cs)

        # 3. Tô màu các ô
        if active_last_move:
            if active_last_move.src:
                painter.fillRect(get_cell_rect(*active_last_move.src), COLOR_LAST_MOVE)
            if active_last_move.dst:
                painter.fillRect(get_cell_rect(*active_last_move.dst), COLOR_LAST_MOVE)

        if self.pending_move:
            if self.pending_move.src:
                painter.fillRect(get_cell_rect(*self.pending_move.src), COLOR_LAST_MOVE)
            if self.pending_move.dst:
                painter.fillRect(get_cell_rect(*self.pending_move.dst), COLOR_POSSIBLE)

        for dr, dc in dest_moves:
            painter.fillRect(get_cell_rect(dr, dc), COLOR_POSSIBLE)

        if self.selected_cell and self.pending_move is None:
            sq_sel = self.game.board.sq(*self.selected_cell)
            if not sq_sel.is_empty:
                sel_color = COLOR_SELECTED if sq_sel.top.owner == self.game.current else COLOR_SELECTED_OPPONENT
                painter.fillRect(get_cell_rect(*self.selected_cell), sel_color)

        # 4. Lưới ô cờ
        painter.setPen(QPen(QColor("#414141"), 1))
        for i in range(10):
            painter.drawLine(int(bx + i * cs), int(by), int(bx + i * cs), int(by + bw))
            painter.drawLine(int(bx), int(by + i * cs), int(bx + bw), int(by + i * cs))

        painter.setPen(QPen(QColor("#1b0e03"), 2))
        painter.drawRect(self.board_rect)

        # 5. Nhãn tọa độ (Bật / Tắt theo show_coordinates)
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

        # 6. Vẽ các quân cờ
        piece_size = cs * 0.88
        pending = self.pending_move
        badge_overlays = []

        for r in range(9):
            for c in range(9):
                if pending:
                    if pending.src == (r, c):
                        sq = self.game.board.sq(r, c)
                        if pending.kind == 'single' and len(sq.stack) > 1:
                            sr, sc = self._to_screen_coords(r, c)
                            pcx = bx + (sc + 0.5) * cs
                            pcy = by + (sr + 0.5) * cs
                            remaining_len = len(sq.stack) - 1
                            self._draw_piece(
                                painter, sq.stack[-2],
                                pcx, pcy,
                                piece_size, stack_len=remaining_len,
                                opacity=1.0,
                            )
                            if remaining_len > 1:
                                badge_overlays.append((pcx, pcy, piece_size, remaining_len, sq.stack[-2].owner))
                        continue
                    if pending.dst == (r, c):
                        continue

                sq = self.game.board.sq(r, c)
                if not sq.is_empty:
                    sr, sc = self._to_screen_coords(r, c)
                    opacity = 0.45 if (r, c) in dest_moves else 1.0
                    pcx = bx + (sc + 0.5) * cs
                    pcy = by + (sr + 0.5) * cs
                    self._draw_piece(
                        painter, sq.top,
                        pcx, pcy,
                        piece_size, stack_len=len(sq.stack),
                        opacity=opacity,
                    )
                    if len(sq.stack) > 1:
                        badge_overlays.append((pcx, pcy, piece_size, len(sq.stack), sq.top.owner))

        # 7. Quân preview ở ô đích (bao gồm xoay tự do khi chưa xác nhận)
        if pending:
            target_pos = pending.dst or pending.src
            if target_pos:
                sdr, sdc = self._to_screen_coords(*target_pos)
                cx, cy = bx + (sdc + 0.5) * cs, by + (sdr + 0.5) * cs

                if pending.kind == 'drop':
                    preview_piece = Piece(pending.ptype, self.game.current, (pending.facing or 0) % 4)
                    dst_sq = self.game.board.sq(*pending.dst)
                    base = len(dst_sq.stack) if (not dst_sq.is_empty and dst_sq.owner == self.game.current) else 0
                    preview_len = base + 1
                    self._draw_piece(painter, preview_piece, cx, cy, piece_size, stack_len=preview_len, opacity=1.0)
                    if preview_len > 1:
                        badge_overlays.append((cx, cy, piece_size, preview_len, preview_piece.owner))
                    self._draw_facing_label(painter, cx, cy, piece_size, (pending.facing or 0) % 4)
                elif pending.kind == 'rotate':
                    sq_src = self.game.board.sq(*pending.src)
                    if not sq_src.is_empty:
                        moving_top = sq_src.top
                        final_facing = (moving_top.facing + pending.rotate_after) % 4
                        preview_piece = Piece(moving_top.ptype, moving_top.owner, final_facing)
                        preview_len = len(sq_src.stack)
                        self._draw_piece(painter, preview_piece, cx, cy, piece_size, stack_len=preview_len, opacity=1.0)
                        if preview_len > 1:
                            badge_overlays.append((cx, cy, piece_size, preview_len, preview_piece.owner))
                        self._draw_facing_label(painter, cx, cy, piece_size, final_facing)
                else:
                    sq_src = self.game.board.sq(*pending.src)
                    if not sq_src.is_empty:
                        moving_top = sq_src.top
                        final_facing = (moving_top.facing + pending.rotate_after) % 4
                        preview_piece = Piece(moving_top.ptype, moving_top.owner, final_facing)
                        dst_sq = self.game.board.sq(*pending.dst)
                        total_stack = len(sq_src.stack) if pending.kind == 'team' else (
                            (len(dst_sq.stack) if not dst_sq.is_empty and dst_sq.owner == self.game.current else 0) + 1
                        )
                        self._draw_piece(painter, preview_piece, cx, cy, piece_size, stack_len=total_stack, opacity=1.0)
                        if total_stack > 1:
                            badge_overlays.append((cx, cy, piece_size, total_stack, preview_piece.owner))
                        if pending.ptype not in NON_ROTATABLE:
                            self._draw_facing_label(painter, cx, cy, piece_size, final_facing)

        # 8. Chú thích mũi tên / vòng tròn (phải chuột hoặc Ctrl+trái chuột)
        self._draw_annotations(painter)

        # 8.1 MultiPV Analysis Arrows from Engine
        self._draw_engine_arrows(painter)

        # 9. Stack badges are always the topmost layer.
        for bcx, bcy, bsize, blen, bowner in badge_overlays:
            self._draw_stack_badge(painter, bcx, bcy, bsize, blen, bowner)

    def _draw_facing_label(self, painter: QPainter, cx: float, cy: float, size: float, facing: int):
        """Small badge showing the pending facing as a number: 0=up,1=right,2=down,3=left."""
        r = max(9, int(size * 0.16))
        label_rect = QRectF(cx - size / 2.0 - r * 0.4, cy - size / 2.0 - r * 0.4, r * 2, r * 2)
        painter.save()
        painter.setBrush(QBrush(QColor("#1683c5")))
        painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
        painter.drawEllipse(label_rect)
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.setFont(QFont("Segoe UI", max(7, int(r * 0.95)), QFont.Weight.Bold))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, str(facing))
        painter.restore()

    def _draw_piece(
        self,
        painter: QPainter,
        piece: Piece,
        cx: float,
        cy: float,
        size: float,
        stack_len: int = 1,
        opacity: float = 1.0,
    ):
        side_str = 'xanh' if piece.owner == Player.XANH else 'cam'
        p_name = "ky" if piece.ptype.name.lower() == "ki" else piece.ptype.name.lower()
        svg_path = os.path.join(DIR_PIECES, f"{side_str}_{p_name}.svg")
        renderer = SvgHelper.get_renderer(svg_path)

        visual_facing = int(piece.facing or 0)
        if self.is_flipped:
            visual_facing = (visual_facing + 2) % 4

        # Render độc lập ra QPixmap để triệt tiêu ảnh hưởng góc xoay
        pix_dim = int(size * 2)
        pixmap = QPixmap(pix_dim, pix_dim)
        pixmap.fill(Qt.GlobalColor.transparent)

        p_pix = QPainter(pixmap)
        p_pix.setRenderHint(QPainter.RenderHint.Antialiasing)
        p_pix.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        p_pix.translate(pix_dim / 2.0, pix_dim / 2.0)
        p_pix.rotate(visual_facing * 90)
        draw_rect = QRectF(-pix_dim / 2.0, -pix_dim / 2.0, pix_dim, pix_dim)

        if renderer and renderer.isValid():
            renderer.render(p_pix, draw_rect)
        else:
            color = QColor("#2e7d32") if side_str == 'xanh' else QColor("#e65100")
            p_pix.setBrush(QBrush(color))
            p_pix.setPen(QPen(Qt.GlobalColor.white, 2))
            p_pix.drawRoundedRect(draw_rect.adjusted(4, 4, -4, -4), 8, 8)
            p_pix.setPen(QPen(Qt.GlobalColor.white))
            p_pix.setFont(QFont("Segoe UI", max(8, int(pix_dim * 0.28)), QFont.Weight.Bold))
            p_pix.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter, piece.code())

        p_pix.end()

        # Vẽ Pixmap lên bàn cờ
        painter.save()
        painter.setOpacity(opacity)
        target_rect = QRectF(cx - size / 2.0, cy - size / 2.0, size, size)
        painter.drawPixmap(target_rect.toRect(), pixmap)

        painter.restore()

    def _draw_stack_badge(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        size: float,
        stack_len: int,
        owner: Player,
    ):
        """Draw stack count centered exactly on the piece's bottom-right outer corner."""
        if stack_len <= 1:
            return
        badge_r = max(7, int(self.cell_size * 0.15))
        badge_cx = cx + size / 2.0
        badge_cy = cy + size / 2.0
        badge_rect = QRectF(
            badge_cx - badge_r,
            badge_cy - badge_r,
            badge_r * 2.0,
            badge_r * 2.0,
        )
        badge_color = QColor("#ff9800") if owner == Player.CAM else QColor("#4caf50")

        painter.save()
        painter.setOpacity(1.0)
        painter.setBrush(QBrush(badge_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(badge_rect)
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.setFont(QFont("Segoe UI", max(7, int(badge_r * 1.0)), QFont.Weight.Bold))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(stack_len))
        painter.restore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if (
                self.annot_circles
                or self.annot_arrows
                or self._annot_drag_start is not None
            ):
                self._clear_annotations()
                self._annot_dragging_ctrl = False
                self.update()
                event.accept()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        pos = event.position()

        is_right = event.button() == Qt.MouseButton.RightButton
        is_ctrl_left = (
            event.button() == Qt.MouseButton.LeftButton
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        )

        if is_right or is_ctrl_left:
            cell = self._pos_to_cell(pos)
            if cell is not None:
                self._annot_drag_start = cell
                self._annot_drag_current = cell
                self._annot_dragging_ctrl = is_ctrl_left
                self.update()
            return

        # A plain left click (no ctrl) clears any annotations first,
        # same convention as chess.com/lichess.
        if event.button() == Qt.MouseButton.LeftButton and (self.annot_circles or self.annot_arrows):
            self._clear_annotations()
            self.update()

        if not self.board_rect.contains(pos):
            return

        bx, by = self.board_rect.x(), self.board_rect.y()
        cs = self.cell_size
        display_c = max(0, min(8, int((pos.x() - bx) // cs)))
        display_r = max(0, min(8, int((pos.y() - by) // cs)))
        row, col = self._to_matrix_coords(display_r, display_c)

        # Even when moves are disabled or position is terminal, allow clicking any stack/piece
        # (own or opponent) to inspect it in the top-right StackInspectorWidget.
        if not self.moves_enabled or self._is_position_blocked():
            sq = self.game.board.sq(row, col)
            if self.selected_cell == (row, col) or sq.is_empty:
                self._set_selection(None)
            else:
                self._set_selection((row, col))
            return

        if self.pending_move is not None:
            if self.pending_move.src == (row, col) or self.pending_move.dst == (row, col):
                self._cancel_pending()
                self._set_selection((row, col))
            return

        legal = self._legal_moves()

        if self.selected_hand_piece is not None:
            drop_moves = [
                m for m in legal
                if m.kind == 'drop' and m.dst == (row, col) and m.ptype == self.selected_hand_piece
            ]
            if drop_moves:
                selected_drop = drop_moves[0]
                if selected_drop.ptype in NON_ROTATABLE:
                    commit_move = Move(
                        kind='drop',
                        dst=selected_drop.dst,
                        ptype=selected_drop.ptype,
                        facing=selected_drop.facing,
                        rotate_after=0,
                    )
                    if self._commit_move(commit_move):
                        self.selected_hand_piece = None
                        self.last_move = commit_move
                        self._cancel_pending()
                        self._set_selection(None)
                        self._clear_annotations()
                        self.moveMade.emit(commit_move)
                        self.update()
                    return

                init_f = initial_facing(self.game.current)
                self.pending_move = Move(
                    kind='drop',
                    dst=(row, col),
                    ptype=self.selected_hand_piece,
                    facing=init_f,
                    rotate_after=0,
                )
                self.selected_hand_piece = None
                self._sync_toolbar_state()
                self.update()
            return

        if self.selected_cell is None:
            sq = self.game.board.sq(row, col)
            if not sq.is_empty:
                if sq.top.owner == self.game.current and len(sq.stack) <= 1 and self.toolbar:
                    self.toolbar.set_team_mode(False)
                    self.is_team_mode = False
                self._set_selection((row, col))
            return

        src_r, src_c = self.selected_cell
        if (src_r, src_c) == (row, col):
            self._set_selection(None)
            return

        sel_sq = self.game.board.sq(src_r, src_c)
        if sel_sq.is_empty or sel_sq.top.owner != self.game.current:
            sq = self.game.board.sq(row, col)
            if not sq.is_empty:
                if sq.top.owner == self.game.current and len(sq.stack) <= 1 and self.toolbar:
                    self.toolbar.set_team_mode(False)
                    self.is_team_mode = False
                self._set_selection((row, col))
            else:
                self._set_selection(None)
            return

        wanted_kind = 'team' if self.is_team_mode else 'single'
        matched_move = next(
            (m for m in legal if m.src == (src_r, src_c) and m.dst == (row, col) and m.kind == wanted_kind),
            next((m for m in legal if m.src == (src_r, src_c) and m.dst == (row, col) and m.kind == 'single'), None)
        )

        if not matched_move:
            sq = self.game.board.sq(row, col)
            if not sq.is_empty:
                if sq.top.owner == self.game.current and len(sq.stack) <= 1 and self.toolbar:
                    self.toolbar.set_team_mode(False)
                    self.is_team_mode = False
                self._set_selection((row, col))
            else:
                self._set_selection(None)
            return

        if matched_move.ptype in NON_ROTATABLE:
            commit_move = Move(
                kind=matched_move.kind,
                src=matched_move.src,
                dst=matched_move.dst,
                ptype=matched_move.ptype,
                facing=matched_move.facing,
                rotate_after=0,
            )
            if self._commit_move(commit_move):
                self.last_move = commit_move
                self._cancel_pending()
                self._set_selection(None)
                self._clear_annotations()
                self.moveMade.emit(commit_move)
                self.update()
        else:
            self.pending_move = Move(
                kind=matched_move.kind,
                src=matched_move.src,
                dst=matched_move.dst,
                ptype=matched_move.ptype,
                facing=matched_move.facing,
                rotate_after=0,
            )
            self._sync_toolbar_state()
            self.update()

    def mouseMoveEvent(self, event):
        if self._annot_drag_start is not None:
            cell = self._pos_to_cell(event.position())
            if cell != self._annot_drag_current:
                self._annot_drag_current = cell
                self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        is_right = event.button() == Qt.MouseButton.RightButton
        is_ctrl_left = (
            event.button() == Qt.MouseButton.LeftButton and self._annot_dragging_ctrl
        )

        if (is_right or is_ctrl_left) and self._annot_drag_start is not None:
            start = self._annot_drag_start
            end = self._pos_to_cell(event.position())

            if end is not None:
                if end == start:
                    # toggle circle
                    if start in self.annot_circles:
                        self.annot_circles.discard(start)
                    else:
                        self.annot_circles.add(start)
                else:
                    key = (start, end)
                    if key in self.annot_arrows:
                        self.annot_arrows.discard(key)
                    else:
                        self.annot_arrows.add(key)

            self._annot_drag_start = None
            self._annot_drag_current = None
            self._annot_dragging_ctrl = False
            self.update()
            return

        super().mouseReleaseEvent(event)


class EngineArrowOverlay(QWidget):
    """Transparent overlay spanning board_row_widget (left komadai, board, right komadai)
    to render MultiPV arrows seamlessly across trays and board.
    Drop moves start directly from the piece item on the player's Komadai stand.
    """

    def __init__(self, board_row_widget, board, komadai_cam, komadai_xanh, parent=None):
        super().__init__(parent or board_row_widget)
        self.board_row_widget = board_row_widget
        self.board = board
        self.komadai_cam = komadai_cam
        self.komadai_xanh = komadai_xanh

        self.setObjectName("engineArrowOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event):
        if self.rect() != self.board_row_widget.rect():
            self.setGeometry(self.board_row_widget.rect())

        board = self.board
        if board is None:
            return
        if not getattr(board, "show_engine_arrows", True):
            return
        engine_arrows = getattr(board, "engine_arrows", {})
        if not engine_arrows:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        specs = {
            1: {
                "color": QColor(22, 163, 74, 215),   # #16A34A (Xanh lá), alpha 215
                "pen_style": Qt.PenStyle.SolidLine,
                "width": 6.0,
                "head_len": 16.0,
                "angle_deg": 35.0,
            },
            2: {
                "color": QColor(37, 99, 235, 185),   # #2563EB (Xanh dương), alpha 185
                "pen_style": Qt.PenStyle.SolidLine,
                "width": 4.5,
                "head_len": 13.0,
                "angle_deg": 30.0,
            },
            3: {
                "color": QColor(245, 158, 11, 170),  # #F59E0B (Cam hổ phách), alpha 170
                "pen_style": Qt.PenStyle.DashLine,
                "width": 3.5,
                "head_len": 11.0,
                "angle_deg": 25.0,
            },
        }

        max_arr = getattr(board, "max_engine_arrows", 3)
        active_ranks = [rk for rk in (1, 2, 3) if rk in engine_arrows and rk <= max_arr]
        if not active_ranks:
            return

        # MultiPV arrows offset if overlapping
        offsets = {1: 0.0, 2: 0.0, 3: 0.0}
        shift = getattr(board, "cell_size", 40.0) * 0.09
        if 1 in active_ranks and 2 in active_ranks:
            a1, a2 = engine_arrows[1], engine_arrows[2]
            if a1.get("src") == a2.get("src") and a1.get("dst") == a2.get("dst") and a1.get("kind") == a2.get("kind"):
                offsets[1] = -shift
                offsets[2] = shift
        if 1 in active_ranks and 3 in active_ranks:
            a1, a3 = engine_arrows[1], engine_arrows[3]
            if a1.get("src") == a3.get("src") and a1.get("dst") == a3.get("dst") and a1.get("kind") == a3.get("kind"):
                offsets[3] = shift * 2.0

        for rk in sorted(active_ranks, reverse=True):
            self._draw_overlay_arrow(painter, engine_arrows[rk], specs[rk], offset_perp=offsets.get(rk, 0.0))

    def _draw_overlay_arrow(self, painter: QPainter, arrow: dict, spec: dict, offset_perp: float = 0.0):
        color = spec["color"]
        pen_style = spec["pen_style"]
        width = spec["width"]
        head_len = spec["head_len"]
        angle_rad = math.radians(spec["angle_deg"])

        src = arrow.get("src")
        dst = arrow.get("dst")
        if dst is None:
            return

        # Cell center on board
        if isinstance(dst, (tuple, list)):
            p2_board = self.board._cell_center(dst[0], dst[1])
        else:
            p2_board = self.board._cell_center(dst // 9, dst % 9)
        p2_raw = self.board.mapTo(self.board_row_widget, p2_board)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        kind = arrow.get("kind", "single")
        is_drop = (kind == "drop") or (src is None)

        cs = getattr(self.board, "cell_size", 40.0)

        if is_drop:
            # === NƯỚC THẢ QUÂN: Mũi tên kéo từ quân trên komadai vào ô dst ===
            cam_moving = arrow.get("cam", True)
            tray = self.komadai_cam if cam_moving else self.komadai_xanh

            # Resolve piece type
            ptype = arrow.get("ptype", "")
            if hasattr(ptype, "name"):
                p_code = ptype.name.lower()
            else:
                p_code = str(ptype).lower()

            if p_code in ("ki", "ky", "k"):
                p_code = "ky"
            elif p_code in ("l", "long"):
                p_code = "long"
            elif p_code in ("p", "phuong"):
                p_code = "phuong"
            elif p_code in ("b", "binh"):
                p_code = "binh"
            elif p_code in ("s", "si"):
                p_code = "si"
            elif p_code in ("t", "tuong"):
                p_code = "tuong"
            elif p_code in ("x", "xa"):
                p_code = "xa"

            target_item = None
            if tray is not None and hasattr(tray, "items"):
                target_item = tray.items.get(p_code)

            if target_item is not None and target_item.width() > 0:
                p1_raw = target_item.mapTo(self.board_row_widget, QPointF(target_item.width() / 2.0, target_item.height() / 2.0))
            elif tray is not None and tray.width() > 0:
                p1_raw = tray.mapTo(self.board_row_widget, QPointF(tray.width() / 2.0, tray.height() / 2.0))
            else:
                dir_y = 1.0 if (cam_moving != getattr(self.board, "is_flipped", False)) else -1.0
                p1_raw = QPointF(p2_raw.x(), p2_raw.y() - dir_y * cs * 1.5)

            dx = p2_raw.x() - p1_raw.x()
            dy = p2_raw.y() - p1_raw.y()
            length = max(1e-6, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            px, py = -uy, ux

            p1 = QPointF(p1_raw.x() + px * offset_perp, p1_raw.y() + py * offset_perp)
            p2 = QPointF(p2_raw.x() + px * offset_perp, p2_raw.y() + py * offset_perp)

            tip_offset = min(cs * 0.12, length * 0.1)
            tip = QPointF(p2.x() - ux * tip_offset, p2.y() - uy * tip_offset)

            base = QPointF(tip.x() - ux * head_len, tip.y() - uy * head_len)
            half_w = head_len * math.tan(angle_rad)
            head_l = QPointF(base.x() + px * half_w, base.y() + py * half_w)
            head_r = QPointF(base.x() - px * half_w, base.y() - py * half_w)

            # Thân mũi tên
            pen = QPen(color, width, pen_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(p1, base)

            # Điểm tròn nhỏ neo tại ô quân trên tay
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(p1, width * 0.9, width * 0.9)

            # Đầu mũi tên tam giác tại ô đích
            arrow_head = QPolygonF([tip, head_l, head_r])
            painter.drawPolygon(arrow_head)

            # Vòng tròn nét đứt quanh ô đích đến trên bàn cờ
            target_pen = QPen(color, max(1.5, width * 0.4), Qt.PenStyle.DashLine)
            painter.setPen(target_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(p2_raw, cs * 0.38, cs * 0.38)

        elif src == dst:
            # === XOAY TẠI CHỖ (Rotate on same square) ===
            center = p2_raw
            radius = cs * 0.32
            pen = QPen(color, width, pen_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            painter.drawArc(arc_rect, int(45 * 16), int(270 * 16))

            end_angle = math.radians(45)
            tip = QPointF(center.x() + radius * math.cos(end_angle), center.y() - radius * math.sin(end_angle))
            tan_x, tan_y = math.sin(end_angle), math.cos(end_angle)
            ux, uy = tan_x, tan_y
            px, py = -uy, ux
            base = QPointF(tip.x() - ux * head_len, tip.y() - uy * head_len)
            half_w = head_len * math.tan(angle_rad)
            head_l = QPointF(base.x() + px * half_w, base.y() + py * half_w)
            head_r = QPointF(base.x() - px * half_w, base.y() - py * half_w)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(QPolygonF([tip, head_l, head_r]))

        else:
            # === NƯỚC ĐI THÔNG THƯỜNG TRÊN BÀN CỜ ===
            if isinstance(src, (tuple, list)):
                p1_board = self.board._cell_center(src[0], src[1])
            else:
                p1_board = self.board._cell_center(src // 9, src % 9)
            p1_raw = self.board.mapTo(self.board_row_widget, p1_board)

            dx, dy = p2_raw.x() - p1_raw.x(), p2_raw.y() - p1_raw.y()
            length = max(1e-6, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            px, py = -uy, ux

            p1 = QPointF(p1_raw.x() + px * offset_perp, p1_raw.y() + py * offset_perp)
            p2 = QPointF(p2_raw.x() + px * offset_perp, p2_raw.y() + py * offset_perp)

            tip_offset = min(cs * 0.12, length * 0.1)
            tip = QPointF(p2.x() - ux * tip_offset, p2.y() - uy * tip_offset)

            base = QPointF(tip.x() - ux * head_len, tip.y() - uy * head_len)
            half_w = head_len * math.tan(angle_rad)
            head_l = QPointF(base.x() + px * half_w, base.y() + py * half_w)
            head_r = QPointF(base.x() - px * half_w, base.y() - py * half_w)

            pen = QPen(color, width, pen_style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(p1, base)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(p1, width * 0.85, width * 0.85)

            arrow_head = QPolygonF([tip, head_l, head_r])
            painter.drawPolygon(arrow_head)

        painter.restore()
