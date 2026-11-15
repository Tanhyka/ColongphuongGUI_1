"""Versioned, atomic settings-backed Qt layout with preset system and free docking."""

from __future__ import annotations

import base64
import json
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QByteArray, QRect, QSettings, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

VERSION = 8

PRESET_DEFAULT = "default"
PRESET_ANALYSIS = "analysis"
PRESET_MULTISCREEN = "multiscreen"
PRESET_SPOTLIGHT = "board_spotlight"
PRESET_MINIMAL = "minimal"

BUILTIN_PRESETS: List[Tuple[str, str, str]] = [
    (PRESET_DEFAULT, "Mặc định (Chuẩn 2 cột)", "Bố cục cân đối: Bàn cờ & Kỳ phổ bên trái, Đồ thị và Phân tích bên dưới"),
    (PRESET_ANALYSIS, "Phân tích Engine & Thi đấu", "Mở rộng bảng MultiPV Engine Thinking và Đồ thị đánh giá"),
    (PRESET_MULTISCREEN, "Đa màn hình (Tách cửa sổ nổi)", "Tách toàn bộ các khung thành các cửa sổ độc lập để kéo thả đa màn hình"),
    (PRESET_SPOTLIGHT, "Bàn cờ Độc lập (Spotlight)", "Chỉ tách riêng Bàn cờ thành cửa sổ lớn độc lập, các công cụ ở cửa sổ chính"),
    (PRESET_MINIMAL, "Tối giản (Bàn cờ & Kỳ phổ)", "Ẩn các bảng phụ, tập trung xem bàn cờ và danh sách nước đi"),
]


def encoded(value):
    return bytes(value.toBase64()).decode("ascii")


def decoded(value):
    return QByteArray(base64.b64decode(value, validate=True))


class LayoutManager:
    """Manages dock widget arrangement presets and user custom presets."""

    SETTINGS_KEY_CUSTOM_PRESETS = "workspace/custom_presets_v8"
    SETTINGS_KEY_STARTUP_PRESET = "workspace/startup_preset"

    @classmethod
    def _settings(cls):
        return QSettings("Colongphuong", "ColongphuongGUI_1")

    @classmethod
    def get_custom_presets(cls) -> Dict[str, Dict[str, str]]:
        settings = cls._settings()
        raw = settings.value(cls.SETTINGS_KEY_CUSTOM_PRESETS, "{}")
        try:
            data = json.loads(str(raw))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    def save_custom_preset(cls, name: str, state_b64: str, geom_b64: str) -> bool:
        presets = cls.get_custom_presets()
        presets[name] = {"state": state_b64, "geometry": geom_b64}
        settings = cls._settings()
        settings.setValue(cls.SETTINGS_KEY_CUSTOM_PRESETS, json.dumps(presets, ensure_ascii=False))
        settings.sync()
        return True

    @classmethod
    def delete_custom_preset(cls, name: str) -> bool:
        presets = cls.get_custom_presets()
        if name in presets:
            del presets[name]
            settings = cls._settings()
            settings.setValue(cls.SETTINGS_KEY_CUSTOM_PRESETS, json.dumps(presets, ensure_ascii=False))
            settings.sync()
            return True
        return False

    @classmethod
    def get_startup_preset(cls) -> str:
        return str(cls._settings().value(cls.SETTINGS_KEY_STARTUP_PRESET, PRESET_DEFAULT))

    @classmethod
    def set_startup_preset(cls, preset_id: str) -> None:
        settings = cls._settings()
        settings.setValue(cls.SETTINGS_KEY_STARTUP_PRESET, preset_id)
        settings.sync()

    @classmethod
    def apply_preset(cls, window, preset_id: str) -> bool:
        """Applies a built-in or custom preset layout to the MainWindow."""
        custom_presets = cls.get_custom_presets()
        if preset_id in custom_presets:
            p_data = custom_presets[preset_id]
            state_bytes = base64.b64decode(p_data["state"])
            geom_bytes = base64.b64decode(p_data["geometry"])
            window.restoreState(QByteArray(state_bytes), VERSION)
            window.restoreGeometry(QByteArray(geom_bytes))
            window._schedule_cluster_update()
            return True

        if preset_id == PRESET_DEFAULT:
            cls.apply_default_layout(window)
            return True
        elif preset_id == PRESET_ANALYSIS:
            cls.apply_analysis_layout(window)
            return True
        elif preset_id == PRESET_MULTISCREEN:
            cls.apply_multiscreen_layout(window)
            return True
        elif preset_id == PRESET_SPOTLIGHT:
            cls.apply_spotlight_layout(window)
            return True
        elif preset_id == PRESET_MINIMAL:
            cls.apply_minimal_layout(window)
            return True

        cls.apply_default_layout(window)
        return False

    @classmethod
    def apply_default_layout(cls, win):
        """Standard 2-column balanced layout."""
        win._default_docks()

    @classmethod
    def apply_analysis_layout(cls, win):
        """Focus on Engine Analysis thinking table and real-time graph."""
        for d in win.all_docks:
            d.setFloating(False)
            win.removeDockWidget(d)

        win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win.winrate_dock)
        win.splitDockWidget(win.winrate_dock, win.board_dock, Qt.Orientation.Vertical)
        win.splitDockWidget(win.board_dock, win.evaluation_dock, Qt.Orientation.Vertical)

        win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, win.thinking_dock)
        win.splitDockWidget(win.thinking_dock, win.notation_dock, Qt.Orientation.Horizontal)
        win.tabifyDockWidget(win.thinking_dock, win.candidates_dock)
        win.tabifyDockWidget(win.thinking_dock, win.possible_moves_dock)
        win.tabifyDockWidget(win.thinking_dock, win.consider_dock)
        win.thinking_dock.raise_()

        for d in win.all_docks:
            d.show()

        win.resizeDocks([win.board_dock, win.thinking_dock], [680, 560], Qt.Orientation.Horizontal)
        win.resizeDocks([win.winrate_dock, win.board_dock, win.evaluation_dock], [58, 480, 240], Qt.Orientation.Vertical)
        win.resizeDocks([win.thinking_dock, win.notation_dock], [380, 280], Qt.Orientation.Horizontal)
        win._schedule_cluster_update()

    @classmethod
    def apply_multiscreen_layout(cls, win):
        """Float all panels so they can be positioned independently across monitors."""
        for dock in win.all_docks:
            dock.setFloating(True)
            dock.show()
        win._schedule_cluster_update()

    @classmethod
    def apply_spotlight_layout(cls, win):
        """Spotlight: Board floats as large independent window, controls docked."""
        cls.apply_default_layout(win)
        win.board_dock.setFloating(True)
        win.board_dock.resize(960, 600)
        win.board_dock.show()
        win.board_dock.raise_()
        win._schedule_cluster_update()

    @classmethod
    def apply_minimal_layout(cls, win):
        """Minimal: Board and Notation only."""
        cls.apply_default_layout(win)
        win.winrate_dock.hide()
        win.evaluation_dock.hide()
        win.thinking_dock.hide()
        win.candidates_dock.hide()
        win.possible_moves_dock.hide()
        win.consider_dock.hide()
        win.board_dock.show()
        win.notation_dock.show()
        win._schedule_cluster_update()


class ManagePresetsDialog(QDialog):
    """Dialog to manage custom user presets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý Bố cục & Preset")
        self.setMinimumSize(420, 320)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Danh sách các Preset bố cục cửa sổ:</b>", self))
        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.btn_load = QPushButton("Áp dụng", self)
        self.btn_delete = QPushButton("Xóa", self)
        self.btn_set_startup = QPushButton("Đặt làm Mặc định", self)
        btn_row.addWidget(self.btn_load)
        btn_row.addWidget(self.btn_delete)
        btn_row.addWidget(self.btn_set_startup)
        layout.addLayout(btn_row)

        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

        self.btn_load.clicked.connect(self._on_load)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_set_startup.clicked.connect(self._on_set_startup)

        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        startup = LayoutManager.get_startup_preset()

        # Builtins
        for p_id, p_name, p_desc in BUILTIN_PRESETS:
            tag = " ★ [Mặc định]" if p_id == startup else ""
            self.list_widget.addItem(f"{p_name}{tag} (Hệ thống)")

        # Customs
        customs = LayoutManager.get_custom_presets()
        for name in sorted(customs.keys()):
            tag = " ★ [Mặc định]" if name == startup else ""
            self.list_widget.addItem(f"{name}{tag} (Tùy chỉnh)")

    def _selected_name(self) -> Optional[Tuple[str, bool]]:
        row = self.list_widget.currentRow()
        if row < 0:
            return None
        if row < len(BUILTIN_PRESETS):
            return BUILTIN_PRESETS[row][0], True
        c_index = row - len(BUILTIN_PRESETS)
        custom_names = sorted(LayoutManager.get_custom_presets().keys())
        if 0 <= c_index < len(custom_names):
            return custom_names[c_index], False
        return None

    def _on_load(self):
        sel = self._selected_name()
        if sel and self.parent():
            LayoutManager.apply_preset(self.parent(), sel[0])
            self.accept()

    def _on_delete(self):
        sel = self._selected_name()
        if not sel:
            return
        if sel[1]:
            QMessageBox.information(self, "Không thể xóa", "Preset hệ thống không thể xóa.")
            return
        if QMessageBox.question(self, "Xác nhận xóa", f"Bạn có chắc muốn xóa preset '{sel[0]}'?") == QMessageBox.StandardButton.Yes:
            LayoutManager.delete_custom_preset(sel[0])
            self._refresh()

    def _on_set_startup(self):
        sel = self._selected_name()
        if not sel:
            return
        LayoutManager.set_startup_preset(sel[0])
        self._refresh()
        QMessageBox.information(self, "Thành công", f"Đã đặt '{sel[0]}' làm preset khởi động mặc định.")


class LayoutActions:
    def _init_layout(self):
        self._last_layout = None
        self._layout_busy = False
        settings = QSettings("Colongphuong", "ColongphuongGUI_1")
        raw = settings.value("workspace/layout_v8", "")
        if raw:
            try:
                if not self._apply_layout(json.loads(raw)):
                    raise ValueError("Unsupported or invalid Qt layout")
            except (ValueError, TypeError, KeyError):
                self._default_docks()
                self.statusBar().showMessage("Đã khôi phục bố cục mặc định.", 8000)
        else:
            startup_preset = LayoutManager.get_startup_preset()
            LayoutManager.apply_preset(self, startup_preset)

        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(1000)
        self._layout_timer.timeout.connect(self._save_layout)
        self._layout_timer.start()
        QTimer.singleShot(0, self._ensure_windows_on_screen)

    def _layout_snapshot(self):
        return {
            "version": VERSION,
            "geometry": encoded(self.saveGeometry()),
            "state": encoded(self.saveState(VERSION)),
        }

    def _apply_layout(self, data):
        if not isinstance(data, dict) or data.get("version") != VERSION:
            return False
        geometry, state = (decoded(data[k]) for k in ("geometry", "state"))
        if not geometry or not state:
            return False
        self._layout_busy = True
        try:
            if not self.restoreState(state, VERSION):
                return False
            if not self.restoreGeometry(geometry):
                return False
            self._ensure_windows_on_screen()
            self._schedule_cluster_update()
            return True
        finally:
            self._layout_busy = False

    def _save_layout(self, explicit=False):
        if getattr(self, "_review_active", False):
            return
        if getattr(self, "_layout_busy", False):
            return
        data = self._layout_snapshot()
        raw = json.dumps(data, sort_keys=True)
        if explicit or raw != self._last_layout:
            settings = QSettings("Colongphuong", "ColongphuongGUI_1")
            settings.setValue("workspace/layout_v8", raw)
            settings.sync()
            self._last_layout = raw
        if explicit:
            self.statusBar().showMessage("Đã lưu bố cục cửa sổ hiện tại.", 4000)

    def _reset_layout(self):
        if hasattr(self, "_leave_review"):
            self._leave_review()
        self._layout_busy = True
        try:
            self._default_docks()
            self._ensure_windows_on_screen()
        finally:
            self._layout_busy = False
        self._save_layout(explicit=True)

    def _ensure_windows_on_screen(self):
        screens = [s.availableGeometry() for s in QGuiApplication.screens()]
        if not screens:
            return
        for window in [self] + [d for d in getattr(self, "all_docks", []) if d.isFloating()]:
            frame = window.frameGeometry()
            title = QRect(frame.x(), frame.y(), max(100, frame.width()), 30)
            if any(s.intersected(title).width() >= 100 and s.intersected(title).height() >= 20 for s in screens):
                continue
            target = screens[0]
            window.resize(min(window.width(), target.width()), min(window.height(), target.height()))
            window.move(target.x() + 20, target.y() + 20)

    def _show_workspace_panel(self, dock, checked):
        dock.setVisible(checked)
        if checked:
            self._ensure_windows_on_screen()
            dock.raise_()
            dock.activateWindow()

    def _save_custom_preset_dialog(self):
        name, ok = QInputDialog.getText(
            self,
            "Lưu Bố cục Mới",
            "Nhập tên định danh cho bố cục hiện tại:",
        )
        if ok and name.strip():
            name = name.strip()
            state_b64 = bytes(self.saveState(VERSION).toBase64()).decode("ascii")
            geom_b64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
            LayoutManager.save_custom_preset(name, state_b64, geom_b64)
            self.statusBar().showMessage(f"Đã lưu preset bố cục: '{name}'", 5000)

    def _manage_presets_dialog(self):
        dlg = ManagePresetsDialog(self)
        dlg.exec()
