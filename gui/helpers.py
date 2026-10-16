"""SVG rendering cache helper and reusable panel widget."""

import os
from typing import Optional, Dict
from PyQt6.QtWidgets import QFrame
from PyQt6.QtSvg import QSvgRenderer
from gui.constants import PANEL, BORDER


class SvgHelper:
    """Caches loaded QSvgRenderer instances to optimize rendering performance."""

    renderers: Dict[str, QSvgRenderer] = {}

    @classmethod
    def get_renderer(cls, path: str) -> Optional[QSvgRenderer]:
        if path not in cls.renderers and os.path.isfile(path):
            renderer = QSvgRenderer(path)
            if renderer.isValid():
                cls.renderers[path] = renderer
        return cls.renderers.get(path)


class Panel(QFrame):
    """Standardized styled frame container for GUI components."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setStyleSheet(f"""
            QFrame#Panel {{
                background: {PANEL};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
        """)