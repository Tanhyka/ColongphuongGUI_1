"""Action toolbar component for piece rotation, stacking toggle, and move confirmation."""

import os
from typing import Tuple
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PyQt6.QtCore import pyqtSignal, QSize, Qt, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPainterPath
from PyQt6.QtSvg import QSvgRenderer

from gui.constants import DIR_ICONS

TOOLBAR_BTN_STYLE = """
    QPushButton {
        border: none;
        background: transparent;
        padding: 0px;
        margin: 0px;
    }
    QPushButton:hover {
        opacity: 0.85;
    }
    QPushButton:pressed {
        opacity: 0.70;
    }
    QPushButton:disabled {
        background: transparent;
        border: none;
    }
"""


class ActionToolbar(QWidget):
    """Side toolbar containing rotation, grouping, confirmation, and resignation actions."""

    groupStateChanged = pyqtSignal(bool)
    rotateClicked = pyqtSignal(int)
    tickClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_team_mode: bool = True

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(9)

        self.btn_rot_left = QPushButton()
        self.btn_rot_right = QPushButton()
        self.btn_group = QPushButton()
        self.btn_tick = QPushButton()
        self.btn_resign = QPushButton()

        self.group_icon_info: Tuple[str, str] = ("group.svg", "□")
        self.ungroup_icon_info: Tuple[str, str] = ("ungroup.svg", "▦")

        self.buttons = [
            (self.btn_rot_left, "rotate_left.svg", "↺"),
            (self.btn_rot_right, "rotate_right.svg", "↻"),
            (self.btn_group, self.group_icon_info[0], self.group_icon_info[1]),
            (self.btn_tick, "tick.svg", "✓"),
            (self.btn_resign, "resign.svg", "⚑"),
        ]

        for button, _, _ in self.buttons:
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.layout.addWidget(button)

        # No trailing stretch: a fixed-height 5-button toolbar needs exactly
        # four gaps, otherwise Qt may compress/overlap the fixed-size buttons.

        self.btn_group.clicked.connect(self._toggle_group_state)
        self.btn_rot_left.clicked.connect(lambda: self.rotateClicked.emit(-1))
        self.btn_rot_right.clicked.connect(lambda: self.rotateClicked.emit(1))
        self.btn_tick.clicked.connect(self.tickClicked.emit)

        self.set_piece_selected_state(False, can_team=False, can_tick=False, can_rotate=False)
        self._button_dim = 28
        self.update_scale(54)

    def _create_rounded_icon(self, svg_path: str, dim: int, radius: int) -> QIcon:
        """Renders an SVG file directly into a clipped rounded QIcon."""
        if not os.path.isfile(svg_path):
            return QIcon()

        renderer = QSvgRenderer(svg_path)
        if not renderer.isValid():
            return QIcon()

        def _render_pixmap(opacity: float = 1.0) -> QPixmap:
            pixmap = QPixmap(dim, dim)
            pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setOpacity(opacity)

            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, dim, dim), radius, radius)
            painter.setClipPath(path)

            renderer.render(painter, QRectF(0, 0, dim, dim))
            painter.end()
            return pixmap

        icon = QIcon()
        icon.addPixmap(_render_pixmap(1.0), QIcon.Mode.Normal)
        # Disabled actions must remain legible instead of nearly invisible.
        icon.addPixmap(_render_pixmap(0.58), QIcon.Mode.Disabled)
        return icon

    @staticmethod
    def button_dimension(cell_size: float) -> int:
        # Smaller icons than before: the board stays the visual focus.
        return max(24, min(36, round(cell_size * 0.44)))

    @staticmethod
    def button_spacing(cell_size: float) -> int:
        # Scale the spaces *between* buttons, not only the SVG artwork.
        return max(8, min(15, round(cell_size * 0.19)))

    @staticmethod
    def board_gap(cell_size: float) -> int:
        return max(6, min(12, round(cell_size * 0.11)))

    def update_scale(self, cell_size: float):
        """Resize buttons and full layout together, preventing icon overlap."""
        btn_dim = self.button_dimension(cell_size)
        spacing = self.button_spacing(cell_size)
        radius = max(3, round(btn_dim * 0.11))
        self._button_dim = btn_dim
        self.layout.setSpacing(spacing)
        # Exactly five buttons and four gaps (no trailing spacer).
        self.setFixedSize(btn_dim, 5 * btn_dim + 4 * spacing)

        for button, filename, fallback in self.buttons:
            if button == self.btn_group:
                filename, fallback = self.group_icon_info if self.is_team_mode else self.ungroup_icon_info
            button.setFixedSize(btn_dim, btn_dim)
            button.setIconSize(QSize(btn_dim, btn_dim))
            self._apply_style(button, filename, fallback, radius, btn_dim)

    def _apply_style(self, button: QPushButton, filename: str, fallback: str, radius: int, dim: int):
        path = os.path.join(DIR_ICONS, filename)
        if os.path.isfile(path):
            button.setIcon(self._create_rounded_icon(path, dim, radius))
            button.setText("")
        else:
            button.setIcon(QIcon())
            button.setText(fallback)

        button.setStyleSheet(TOOLBAR_BTN_STYLE)

    def _toggle_group_state(self):
        self.set_team_mode(not self.is_team_mode)
        self.groupStateChanged.emit(self.is_team_mode)

    def set_team_mode(self, is_team_mode: bool):
        """Updates team/single move mode and toggles button icon."""
        self.is_team_mode = bool(is_team_mode)
        btn_dim = getattr(self, '_button_dim', 28)
        radius = max(3, int(btn_dim * 0.10))
        filename, fallback = self.group_icon_info if self.is_team_mode else self.ungroup_icon_info
        self._apply_style(self.btn_group, filename, fallback, radius, btn_dim)

    def set_piece_selected_state(self, selected: bool, can_team: bool = False, can_tick: bool = False, can_rotate: bool = False):
        """Enables or disables action buttons based on board selection state."""
        self.btn_rot_left.setEnabled(bool(can_rotate))
        self.btn_rot_right.setEnabled(bool(can_rotate))
        self.btn_group.setEnabled(bool(can_team))
        self.btn_tick.setEnabled(bool(can_tick))