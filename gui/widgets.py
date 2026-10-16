"""Reusable GUI widgets: hand piece slots, Komadai panels, player cards, and stack inspector."""

import os
from typing import Optional, List, Dict
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QPen, QBrush, QFont
from PyQt6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QScrollBar
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal

from engine.pieces import Piece, Player, PieceType
from gui.constants import DIR_PIECES
from gui.helpers import SvgHelper

PIECE_TYPE_MAP: Dict[str, PieceType] = {
    'long': PieceType.LONG,
    'phuong': PieceType.PHUONG,
    'xa': PieceType.XA,
    'ky': PieceType.KI,
    'si': PieceType.SI,
    'tuong': PieceType.TUONG,
    'binh': PieceType.BINH,
}


class HandPieceItem(QWidget):
    """Clickable square representing a captured/reserve piece in the Komadai."""

    clicked = pyqtSignal(str, str)

    def __init__(self, side: str = "xanh", piece_type: str = "binh", count: int = 0, parent=None):
        super().__init__(parent)
        self.side: str = side
        self.piece_type: str = piece_type
        self.count: int = count
        self.is_selected: bool = False
        self.is_flipped: bool = False

        self.setFixedSize(52, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_tile_size(self, tile_size: int):
        tile_size = max(28, int(tile_size))
        if self.width() != tile_size or self.height() != tile_size:
            self.setFixedSize(tile_size, tile_size)
            self.update()

    def set_count(self, count: int):
        self.count = count
        if self.count == 0:
            self.is_selected = False
        self.update()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update()

    def set_flipped(self, is_flipped: bool):
        self.is_flipped = is_flipped
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.count > 0:
            self.clicked.emit(self.side, self.piece_type)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Artwork scales with the hand tile; retain a dedicated corner for
        # the quantity badge instead of shrinking small komadai pieces too far.
        badge_radius = max(5.5, min(11.0, self.width() * 0.16))
        offset = 2.0
        size = float(max(16, self.width() - badge_radius - offset - 2.0))
        rect = QRectF(offset, offset, size, size)

        painter.setOpacity(1.0 if self.count > 0 else 0.28)

        p_name = "ky" if self.piece_type == "ki" else self.piece_type
        renderer = SvgHelper.get_renderer(os.path.join(DIR_PIECES, f"{self.side}_{p_name}.svg"))

        # Render piece SVG with rotation sync
        painter.save()
        painter.translate(rect.center())

        rotation = 0
        if self.side == "cam":
            rotation += 180
        if self.is_flipped:
            rotation += 180
        painter.rotate(rotation % 360)

        target_rect = QRectF(-size / 2.0, -size / 2.0, size, size)
        if renderer:
            renderer.render(painter, target_rect)
        else:
            color = QColor("#2e7d32") if self.side == "xanh" else QColor("#e65100")
            painter.setPen(QPen(color, 1))
            painter.drawRect(target_rect)
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(target_rect, Qt.AlignmentFlag.AlignCenter, self.piece_type[:2].upper())
        painter.restore()

        # Selection highlight border
        if self.is_selected and self.count > 0:
            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor("#2196f3"), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

        # Quantity badge
        if self.count > 0:
            painter.setOpacity(1.0)
            badge_r = badge_radius
            # Exact intersection of the piece's outer right and bottom edges.
            badge_cx = rect.right()
            badge_cy = rect.bottom()
            badge_color = QColor("#ff9800") if self.side == "cam" else QColor("#4caf50")

            painter.setBrush(QBrush(badge_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)

            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Segoe UI", max(7, round(self.width() * 0.15)), QFont.Weight.Bold))
            badge_rect = QRectF(badge_cx - badge_r, badge_cy - badge_r, badge_r * 2.0, badge_r * 2.0)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(self.count))


class KomadaiWidget(QFrame):
    """Sidebar stand displaying captured prisoners and reserved pieces."""

    pieceSelected = pyqtSignal(str, object)

    def __init__(self, side: str = "xanh", parent=None):
        super().__init__(parent)
        self.side: str = side
        self.is_flipped: bool = False
        self.items: Dict[str, HandPieceItem] = {}

        self.setFixedSize(180, 210)  # initial size; updated with BoardCanvas cells
        self.setStyleSheet("""
            QFrame {
                border: 1px solid #d5d9de;
                border-radius: 8px;
                background-color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        side_title = "CAM" if self.side == "cam" else "XANH"
        side_color = "#e65100" if self.side == "cam" else "#2e7d32"
        self.lbl_side = QLabel(side_title)
        self.lbl_side.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_side.setStyleSheet(f"""
            QLabel {{
                color: {side_color};
                font-family: 'Segoe UI';
                font-weight: 800;
                font-size: 12px;
                border: none;
                letter-spacing: 1px;
                padding-bottom: 2px;
            }}
        """)
        layout.addWidget(self.lbl_side)

        rows_data = [
            [("ky", 0), ("xa", 0)],
            [("si", 0), ("tuong", 0)],
            [("binh", 0), ("phuong", 1), ("long", 1)],
        ]

        for row in rows_data:
            h_box = QHBoxLayout()
            h_box.setSpacing(4)
            h_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            for p_code, count in row:
                item = HandPieceItem(side=self.side, piece_type=p_code, count=count)
                item.clicked.connect(self._on_item_clicked)
                self.items[p_code] = item
                h_box.addWidget(item)
            layout.addLayout(h_box)

    def set_scale(self, cell_size: float):
        """Keep stand and all hand pieces proportional to the board cells."""
        tile = max(28, min(80, round(cell_size * 0.84)))
        if getattr(self, '_tile_size', None) == tile:
            return
        self._tile_size = tile
        for item in self.items.values():
            item.set_tile_size(tile)
        stand_w = 3 * tile + 2 * 4 + 2 * 6
        stand_h = 3 * tile + 45
        self.setFixedSize(stand_w, stand_h)

    def set_flipped(self, is_flipped: bool):
        """Synchronizes flipped board state with piece rotation."""
        self.is_flipped = is_flipped
        for item in self.items.values():
            item.set_flipped(is_flipped)
        self.update()

    def _on_item_clicked(self, side: str, piece_type: str):
        ptype = PIECE_TYPE_MAP.get(piece_type)
        for code, item in self.items.items():
            item.set_selected(not item.is_selected if code == piece_type else False)

        if ptype:
            self.pieceSelected.emit(self.side, ptype)

    def clear_selection(self):
        for item in self.items.values():
            item.set_selected(False)

    def update_counts(self, board, player: Player):
        """Refreshes counts of reserved and captured pieces."""
        res = board.reserve[player]
        pris = board.prisoners[player]
        self.items['long'].set_count(res.count(PieceType.LONG) + pris.count(PieceType.LONG))
        self.items['phuong'].set_count(res.count(PieceType.PHUONG) + pris.count(PieceType.PHUONG))

        for code, p_type in [
            ('xa', PieceType.XA),
            ('ky', PieceType.KI),
            ('si', PieceType.SI),
            ('tuong', PieceType.TUONG),
            ('binh', PieceType.BINH),
        ]:
            self.items[code].set_count(pris.count(p_type))


class PlayerCardWidget(QFrame):
    """Player card widget for displaying avatar, name, and ranking info."""

    def __init__(self, side: str = "cam", side_symbol: str = "☗", parent=None):
        super().__init__(parent)
        self.side: str = side
        self.side_symbol: str = side_symbol
        self.player_name: str = ""
        self.player_rank_text: str = ""
        self.clock_text: str = ""
        self.runtime_status_text: str = ""
        self.avatar_pixmap: Optional[QPixmap] = None

        self.setFixedWidth(180)
        self.setObjectName("PlayerCard")
        self.setStyleSheet("""
            QFrame#PlayerCard {
                border: 1px solid #d5d9de;
                border-radius: 8px;
                background-color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.avatar_box = QLabel()
        self.avatar_box.setFixedSize(160, 160)
        self.avatar_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_box.setScaledContents(True)
        layout.addWidget(self.avatar_box)

        self.lbl_name = QLabel()
        self.lbl_name.setStyleSheet("font-weight: bold; font-size: 13px; color: #1e293b; border: none;")
        self.lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_name)

        self.lbl_rank = QLabel()
        self.lbl_rank.setStyleSheet("font-size: 11px; color: #64748b; border: none;")
        self.lbl_rank.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_rank)

        self.lbl_clock = QLabel()
        self.lbl_clock.setStyleSheet("font-weight: bold; font-size: 13px; color: #111827; border: none;")
        self.lbl_clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_clock)

        self.lbl_runtime_status = QLabel()
        self.lbl_runtime_status.setStyleSheet("font-size: 10px; color: #64748b; border: none;")
        self.lbl_runtime_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_runtime_status)

        self._update_display()

    def set_player_name(self, name: str):
        self.player_name = (name or "").strip()
        self._update_display()

    def set_ranking(self, rank_text: str):
        self.player_rank_text = (rank_text or "").strip()
        self._update_display()

    def set_clock_text(self, text: str):
        self.clock_text = (text or "").strip()
        self._update_display()

    def set_runtime_status(self, text: str):
        self.runtime_status_text = (text or "").strip()
        self._update_display()

    def set_picture(self, image_path: str):
        """Loads and crops avatar image to rounded 160x160 px."""
        if image_path and os.path.isfile(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                size = 160
                scaled_pix = pix.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                rounded = QPixmap(size, size)
                rounded.fill(Qt.GlobalColor.transparent)

                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(0, 0, size, size, 8, 8)
                painter.setClipPath(path)

                ox = (scaled_pix.width() - size) // 2
                oy = (scaled_pix.height() - size) // 2
                painter.drawPixmap(0, 0, scaled_pix, ox, oy, size, size)
                painter.end()

                self.avatar_pixmap = rounded
        self._update_display()

    def clear_card(self):
        self.player_name = ""
        self.player_rank_text = ""
        self.clock_text = ""
        self.runtime_status_text = ""
        self.avatar_pixmap = None
        self._update_display()

    def _update_display(self):
        has_name = bool(self.player_name)
        has_rank = bool(self.player_rank_text)
        has_clock = bool(self.clock_text)
        has_runtime_status = bool(self.runtime_status_text)
        has_avatar = self.avatar_pixmap is not None

        if not has_name and not has_rank and not has_clock and not has_runtime_status and not has_avatar:
            self.setVisible(False)
            return

        self.setVisible(True)

        if has_avatar:
            self.avatar_box.setPixmap(self.avatar_pixmap)
            self.avatar_box.setStyleSheet("border: 1px solid #d5d9de; border-radius: 8px;")
            self.avatar_box.setVisible(True)
        elif has_rank:
            self.avatar_box.setPixmap(QPixmap())
            self.avatar_box.setText(self.player_rank_text.split()[-1].replace("(", "").replace(")", ""))
            self.avatar_box.setStyleSheet("""
                QLabel {
                    border: 1px solid #c99b3b;
                    border-radius: 8px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffd54f, stop:1 #ff8f00);
                    color: #5d4037;
                    font-weight: bold;
                    font-size: 22px;
                }
            """)
            self.avatar_box.setVisible(True)
        else:
            self.avatar_box.setVisible(False)

        if has_name:
            self.lbl_name.setText(f"{self.side_symbol} {self.player_name}")
            self.lbl_name.setVisible(True)
        else:
            self.lbl_name.setVisible(False)

        if has_rank:
            self.lbl_rank.setText(self.player_rank_text)
            self.lbl_rank.setVisible(True)
        else:
            self.lbl_rank.setVisible(False)

        if has_clock:
            self.lbl_clock.setText(self.clock_text)
            self.lbl_clock.setVisible(True)
        else:
            self.lbl_clock.setVisible(False)

        if has_runtime_status:
            self.lbl_runtime_status.setText(self.runtime_status_text)
            self.lbl_runtime_status.setVisible(True)
        else:
            self.lbl_runtime_status.setVisible(False)


class StackPieceItem(QWidget):
    """Draws a compact piece representation along with its level index in a stack."""

    clicked = pyqtSignal(int)

    def __init__(self, piece: Piece, level: int, is_flipped: bool = False, parent=None):
        super().__init__(parent)
        self.piece: Piece = piece
        self.level: int = level
        self.is_flipped: bool = is_flipped
        self.setFixedSize(40, 40)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = 30.0
        piece_rect = QRectF(2.0, 2.0, size, size)
        target_rect = QRectF(-size / 2.0, -size / 2.0, size, size)

        painter.save()
        painter.translate(piece_rect.center())

        side_str = 'xanh' if self.piece.owner == Player.XANH else 'cam'
        p_name = "ky" if self.piece.ptype.name.lower() == "ki" else self.piece.ptype.name.lower()
        renderer = SvgHelper.get_renderer(os.path.join(DIR_PIECES, f"{side_str}_{p_name}.svg"))

        visual_facing = self.piece.facing or 0
        if self.is_flipped:
            visual_facing = (visual_facing + 2) % 4
        painter.rotate(visual_facing * 90)

        if renderer:
            renderer.render(painter, target_rect)
        else:
            color = QColor("#2e7d32") if side_str == 'xanh' else QColor("#e65100")
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
            painter.drawRoundedRect(target_rect, 4, 4)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(target_rect, Qt.AlignmentFlag.AlignCenter, self.piece.code())
        painter.restore()

        # Level index badge
        badge_r = 7.0
        badge_cx = piece_rect.right()
        badge_cy = piece_rect.bottom()
        badge_color = QColor("#e65100") if self.level == 1 else QColor("#475569")

        painter.setBrush(QBrush(badge_color))
        painter.setPen(QPen(Qt.GlobalColor.white, 1.2))
        painter.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)

        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        badge_rect = QRectF(badge_cx - badge_r, badge_cy - badge_r, badge_r * 2.0, badge_r * 2.0)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(self.level))


    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.level)
        super().mousePressEvent(event)


class StackInspectorWidget(QFrame):
    """Inspector panel revealing pieces in a stack using a 5-piece viewport plus scrollbar."""

    pieceClicked = pyqtSignal(int)
    MAX_VISIBLE_PIECES = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(340)
        self.setFixedHeight(98)
        self.setObjectName("StackInspector")
        self.setStyleSheet("""
            QFrame#StackInspector {
                background: #ffffff;
                border: 1px solid #d5d9de;
                border-radius: 6px;
            }
        """)

        self._stack_pieces: List[Piece] = []
        self._is_flipped: bool = False
        self._coord_name: str = ""

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 4, 6, 4)
        root_layout.setSpacing(3)

        self.lbl_title = QLabel("CHI TIẾT CHỒNG QUÂN")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 800; border: none;")
        root_layout.addWidget(self.lbl_title)

        self.pieces_container = QWidget()
        self.pieces_layout = QHBoxLayout(self.pieces_container)
        self.pieces_layout.setContentsMargins(0, 0, 0, 0)
        self.pieces_layout.setSpacing(6)
        self.pieces_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root_layout.addWidget(self.pieces_container)

        self.scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.scrollbar.setFixedHeight(14)
        self.scrollbar.setSingleStep(1)
        self.scrollbar.setPageStep(1)
        self.scrollbar.setStyleSheet("""
            QScrollBar:horizontal {
                background: #f1f5f9;
                height: 14px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #94a3b8;
                min-width: 28px;
                border-radius: 6px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
        """)
        self.scrollbar.valueChanged.connect(self._render_visible_slice)
        root_layout.addWidget(self.scrollbar)

        self.setVisible(False)
        self.scrollbar.setVisible(False)

    def _clear_pieces(self):
        while self.pieces_layout.count():
            item = self.pieces_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def clear(self):
        """Clears displayed stack pieces and hides widget."""
        self._stack_pieces = []
        self._coord_name = ""
        self._clear_pieces()
        self.scrollbar.setVisible(False)
        self.setVisible(False)

    def _render_visible_slice(self):
        self._clear_pieces()
        if not self._stack_pieces:
            self.setVisible(False)
            return

        start = self.scrollbar.value() if self.scrollbar.isVisible() else 0
        visible = self._stack_pieces[start:start + self.MAX_VISIBLE_PIECES]
        for idx, piece in enumerate(visible, start + 1):
            item = StackPieceItem(piece, level=idx, is_flipped=self._is_flipped)
            item.clicked.connect(self.pieceClicked.emit)
            self.pieces_layout.addWidget(item)

    def set_stack(self, stack_pieces: List[Piece], is_flipped: bool = False, coord_name: str = ""):
        """Populates inspector if cell has 2 or more pieces stacked."""
        if not stack_pieces or len(stack_pieces) < 2:
            self.clear()
            return

        self.setVisible(True)
        self._is_flipped = is_flipped
        self._coord_name = coord_name
        self._stack_pieces = list(reversed(stack_pieces))

        title_suffix = f"Ô {coord_name.upper()}" if coord_name else "CHỒNG QUÂN"
        self.lbl_title.setText(f"CHI TIẾT {title_suffix} ({len(stack_pieces)} QUÂN)")

        overflow = max(0, len(self._stack_pieces) - self.MAX_VISIBLE_PIECES)
        self.scrollbar.blockSignals(True)
        self.scrollbar.setRange(0, overflow)
        # A newly inspected stack always starts from its top five pieces.
        self.scrollbar.setValue(0)
        self.scrollbar.blockSignals(False)
        self.scrollbar.setVisible(overflow > 0)
        self._render_visible_slice()