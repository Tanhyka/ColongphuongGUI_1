"""UI color themes and filesystem path constants for the GUI."""

import os

# --- Color Palette ---
BG = "#f3f5f7"
PANEL = "#ffffff"
BORDER = "#d9dee5"
TEXT = "#1f2937"
TEXT_MUTED = "#64748b"
BLUE = "#1683c5"
BLUE_DARK = "#0f6fa8"
BLUE_LIGHT = "#eaf5fc"
SOFT = "#f7f9fb"

# --- Directory Paths ---
GUI_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(GUI_DIR)
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")

DIR_PIECES = os.path.join(ASSETS_DIR, "pieces")
DIR_BOARD = os.path.join(ASSETS_DIR, "board")
DIR_ICONS = os.path.join(ASSETS_DIR, "icons")

# Default export/import directory resolved dynamically from project root
from engine.session import data_dir
DEFAULT_KYPHO_DIR = str(data_dir() / "records")