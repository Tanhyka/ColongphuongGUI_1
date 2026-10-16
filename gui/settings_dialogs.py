"""Settings dialogs for ColongphuongGUI.

These dialogs provide ShogiGUI-inspired configuration surfaces.  They are
intentionally UI/settings focused; engine execution is connected later by the
analysis subsystem.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from PyQt6.QtCore import Qt, QSettings, QProcess
from engine import registry
from engine.client import Client, split_arguments
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


ORG_NAME = "ColongphuongGUI"
APP_NAME = "ColongphuongGUI"

def _settings() -> QSettings:
    return registry.settings()

def _load_engines():
    return registry.load()

def _save_engines(engines):
    registry.save(engines)

def _engine_names():
    return [e['name'] for e in _load_engines() if registry.playable(e)]


def _dialog_buttons(parent: QWidget) -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=parent,
    )
    box.accepted.connect(parent.accept)
    box.rejected.connect(parent.reject)
    return box


def _engine_combo() -> QComboBox:
    combo = QComboBox()
    names = _engine_names()
    combo.addItems(names if names else ["No engine registered"])
    return combo


class EngineEditDialog(QDialog):
    def __init__(self, engine=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Engine');self.setMinimumWidth(520)
        self.old=engine or {};self.verified=None;self.accept_after_probe=False
        form=QFormLayout(self)
        self.name_edit=QLineEdit(self.old.get('engine_name',self.old.get('name','')));self.name_edit.setReadOnly(True)
        self.author_edit=QLineEdit(self.old.get('author',''));self.author_edit.setReadOnly(True)
        self.path_edit=QLineEdit(self.old.get('path',''))
        self.args_edit=QLineEdit(__import__('subprocess').list2cmdline(self.old.get('args',[])))
        browse=QPushButton('Browse...');browse.clicked.connect(self._browse)
        row=QHBoxLayout();row.addWidget(self.path_edit,1);row.addWidget(browse)
        form.addRow('Engine name',self.name_edit);form.addRow('Author',self.author_edit);form.addRow('Path',row);form.addRow('Arguments',self.args_edit)
        self.metadata_label=QLabel('Select executable, then Verify or OK.');self.metadata_label.setWordWrap(True);form.addRow(self.metadata_label)
        self.options_host=QWidget();self.options_form=QFormLayout(self.options_host);self.option_widgets={};form.addRow(self.options_host)
        self.verify_button=QPushButton('Verify');self.verify_button.clicked.connect(self._probe);form.addRow(self.verify_button)
        form.addRow(_dialog_buttons(self))
        self.client=Client(self);self.client.metadataReady.connect(self._verified);self.client.errorOccurred.connect(self._error)
        self.path_edit.textChanged.connect(self._invalidate);self.args_edit.textChanged.connect(self._invalidate)
    def _invalidate(self):
        self.verified=None;self.accept_after_probe=False;self.client.close();self.verify_button.setEnabled(True);self.metadata_label.setText('Verification required.')
    def _browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Select engine executable','','Executable files (*.exe);;All files (*.*)')
        if path:self.path_edit.setText(path)
    def _probe(self):
        self.verify_button.setEnabled(False);self.metadata_label.setText('Checking CLP-EP v1 handshake...')
        try:self.client.probe(self.path_edit.text().strip(),split_arguments(self.args_edit.text()))
        except Exception as exc:self._error(str(exc))
    def _verified(self,metadata):
        self.verified=metadata;self.verified_path=self.path_edit.text().strip();self.verified_args=split_arguments(self.args_edit.text())
        self.name_edit.setText(metadata['name']);self.author_edit.setText(metadata['author']);self.verify_button.setEnabled(True)
        playable=metadata['capabilities'].get('search')==['legal'] and metadata['capabilities'].get('position')==['rules']
        self.metadata_label.setText(f"Version {metadata['version']} · {metadata['kind']} · {'Playable' if playable else 'Not playable'}\nCapabilities: {metadata['capabilities']}")
        while self.options_form.rowCount():self.options_form.removeRow(0)
        self.option_widgets={}
        for name,definition in metadata.get('options',{}).items():
            spin=QSpinBox();spin.setRange(definition['min'],definition['max']);spin.setValue(self.old.get('options',{}).get(name,definition['default']));self.options_form.addRow(name,spin);self.option_widgets[name]=spin
        if self.accept_after_probe:self.accept()
    def _error(self,message):
        self.verified=None;self.accept_after_probe=False;self.verify_button.setEnabled(True);self.metadata_label.setText(str(message))
    def engine_data(self):
        if self.verified is None:raise ValueError('Executable has not passed handshake probe')
        return {**self.verified,'path':self.verified_path,'args':self.verified_args,'configured_options':{n:w.value() for n,w in self.option_widgets.items()}}
    def accept(self):
        if self.verified is None:self.accept_after_probe=True;self._probe();return
        self.client.close();super().accept()
    def reject(self):self.client.close();super().reject()
    def closeEvent(self,event):self.client.close();super().closeEvent(event)


class EngineListDialog(QDialog):
    """Engine settings -> Engine list, modelled after the supplied screenshot."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Engine list")
        self.resize(620, 440)
        self.engines = _load_engines()

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Engine name", "Author", "Path"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        # ShogiGUI-like faint grid lines, including empty rows.
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.PenStyle.SolidLine)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                color: #202124;
                gridline-color: #e5e7eb;
                border: 1px solid #cfd4da;
                selection-background-color: #dbeafe;
                selection-color: #111827;
            }
            QTableWidget::item {
                padding: 2px 5px;
            }
            QHeaderView::section {
                background-color: #fafafa;
                color: #202124;
                border: none;
                border-right: 1px solid #e5e7eb;
                border-bottom: 1px solid #d7dce1;
                padding: 3px 5px;
            }
        """)

        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.doubleClicked.connect(self._edit_selected)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_set = QPushButton("Set")
        self.btn_delete = QPushButton("Delete")
        self.window_check = QCheckBox("window")
        self.window_check.setChecked(bool(_settings().value("engines/window", False, type=bool)))
        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)

        self.btn_add.clicked.connect(self._add_engine)
        self.btn_set.clicked.connect(self._edit_selected)
        self.btn_delete.clicked.connect(self._delete_selected)
        btn_ok.clicked.connect(self.accept)

        bottom.addWidget(self.btn_add)
        bottom.addWidget(self.btn_set)
        bottom.addWidget(self.btn_delete)
        bottom.addStretch(1)
        bottom.addWidget(self.window_check)
        bottom.addStretch(1)
        bottom.addWidget(btn_ok)
        root.addLayout(bottom)

        self._refresh()

    def _refresh(self):
        # Keep visible empty rows so the faint grid continues through the panel,
        # similar to the Engine list in ShogiGUI.
        visible_rows = max(20, len(self.engines))
        self.table.clearContents()
        self.table.setRowCount(visible_rows)

        for r, engine in enumerate(self.engines):
            self.table.setItem(r, 0, QTableWidgetItem(engine.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(engine.get("author", "")))
            self.table.setItem(r, 2, QTableWidgetItem(engine.get("path", "")))
            self.table.item(r,0).setToolTip(f"Version: {engine.get('version','unverified')}\nKind: {engine.get('kind','unknown')}\nPlayable: {registry.playable(engine)}\nCapabilities: {engine.get('capabilities',{})}")

        self.table.clearSelection()
        self._sync_buttons()

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return -1
        row = rows[0].row()
        # Empty visual rows are only there to draw the grid.
        return row if 0 <= row < len(self.engines) else -1

    def _sync_buttons(self):
        row = self._selected_row()
        enabled = row >= 0
        self.btn_set.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    def _register_dialog(self,dlg,old=None):
        data=dlg.engine_data()
        registry.register(data,data['path'],data['args'],data['configured_options'],old)
        self.engines=_load_engines();self._refresh()

    def _add_engine(self):
        dlg=EngineEditDialog(parent=self)
        if dlg.exec()==QDialog.DialogCode.Accepted:
            try:self._register_dialog(dlg)
            except (ValueError,OSError) as exc:QMessageBox.warning(self,'Engine registration',str(exc))

    def _edit_selected(self):
        row=self._selected_row()
        if row<0:return
        old=self.engines[row];dlg=EngineEditDialog(old,self)
        if dlg.exec()==QDialog.DialogCode.Accepted:
            try:self._register_dialog(dlg,old)
            except (ValueError,OSError) as exc:QMessageBox.warning(self,'Engine registration',str(exc))

    def _delete_selected(self):
        row=self._selected_row()
        if row>=0:
            del self.engines[row];_save_engines(self.engines);self._refresh()

    def accept(self):
        _save_engines(self.engines)
        _settings().setValue("engines/window", self.window_check.isChecked())
        super().accept()


class _TimeBox(QGroupBox):
    def __init__(self, title: str = "Time settings", parent=None):
        super().__init__(title, parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(3)
        self.hours = QSpinBox(); self.hours.setRange(0, 99)
        self.minutes = QSpinBox(); self.minutes.setRange(0, 59); self.minutes.setValue(10)
        self.countdown = QSpinBox(); self.countdown.setRange(0, 999); self.countdown.setValue(30)
        grid.addWidget(QLabel("Time"), 0, 0)
        grid.addWidget(self.hours, 0, 1); grid.addWidget(QLabel("H"), 0, 2)
        grid.addWidget(self.minutes, 0, 3); grid.addWidget(QLabel("M"), 0, 4)
        grid.addWidget(QLabel("Countdown"), 1, 0)
        grid.addWidget(self.countdown, 1, 1); grid.addWidget(QLabel("S"), 1, 2)


class GameSettingsDialog(QDialog):
    """New-game setup dialog inspired by the supplied ShogiGUI Game window.

    Step 3.1.5 is intentionally UI/configuration only.  The selected player
    roles are persisted now and will be consumed by Step 3.2 when the C++ AI
    is allowed to make moves automatically.
    """

    def __init__(self, parent=None, *, allow_start: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Game")
        self.setMinimumSize(640, 555)
        self.resize(680, 610)
        self.start_requested = False
        self._allow_start = bool(allow_start)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 7)
        root.setSpacing(4)

        # --------------------------------------------------------------
        # Players: CAM | swap/toss | XANH
        # --------------------------------------------------------------
        players = QHBoxLayout()
        self.cam_box = self._player_box("Cam")
        self.xanh_box = self._player_box("Xanh")

        middle = QVBoxLayout()
        middle.setContentsMargins(2, 10, 2, 0)
        self.btn_swap = QPushButton("<->")
        self.btn_toss = QPushButton("Toss")
        self.btn_swap.setFixedWidth(46)
        self.btn_toss.setFixedWidth(46)
        self.btn_swap.clicked.connect(self._swap_players)
        self.btn_toss.clicked.connect(self._toss_players)
        middle.addWidget(self.btn_swap)
        middle.addWidget(self.btn_toss)
        middle.addStretch(1)

        players.addWidget(self.cam_box, 1)
        players.addLayout(middle)
        players.addWidget(self.xanh_box, 1)
        root.addLayout(players)

        # --------------------------------------------------------------
        # Time controls
        # --------------------------------------------------------------
        times = QHBoxLayout()
        times.setSpacing(6)
        self.cam_time = _TimeBox("Time settings")

        self.xanh_time_wrap = QGroupBox()
        xanh_outer = QVBoxLayout(self.xanh_time_wrap)
        xanh_outer.setContentsMargins(7, 3, 7, 6)
        self.separate_xanh_time = QCheckBox("Xanh Time settings")
        self.xanh_time = _TimeBox("")
        self.xanh_time.setEnabled(False)
        self.separate_xanh_time.toggled.connect(self.xanh_time.setEnabled)
        xanh_outer.addWidget(self.separate_xanh_time)
        xanh_outer.addWidget(self.xanh_time)

        times.addWidget(self.cam_time, 1)
        times.addWidget(self.xanh_time_wrap, 1)
        root.addLayout(times)

        # --------------------------------------------------------------
        # Optional opening-book surfaces.  They are UI placeholders until
        # engine/book support is implemented later.
        # --------------------------------------------------------------
        books = QHBoxLayout()
        books.setSpacing(6)
        self.cam_book = self._book_box("Cam book")
        self.xanh_book = self._book_box("Xanh book")
        books.addWidget(self.cam_book, 1)
        books.addWidget(self.xanh_book, 1)
        root.addLayout(books)

        # --------------------------------------------------------------
        # Left: start/continuous game.  Right: play settings.
        # --------------------------------------------------------------
        lower = QHBoxLayout()
        lower.setSpacing(6)
        left_col = QVBoxLayout()

        start_box = QGroupBox("Start position")
        sg = QGridLayout(start_box)
        sg.setContentsMargins(8, 6, 8, 6)
        sg.setHorizontalSpacing(6)
        sg.setVerticalSpacing(3)
        self.radio_even = QRadioButton("Even")
        self.radio_even.setChecked(True)
        self.start_variant = QComboBox()
        self.start_variant.addItems(["Standard"])
        self.radio_this = QRadioButton("This position")
        sg.addWidget(self.radio_even, 0, 0)
        sg.addWidget(self.start_variant, 0, 1)
        sg.addWidget(self.radio_this, 1, 0, 1, 2)
        left_col.addWidget(start_box)

        self.continuous_box = QGroupBox("Continuous game")
        self.continuous_box.setCheckable(True)
        self.continuous_box.setChecked(False)
        cg = QGridLayout(self.continuous_box)
        cg.setContentsMargins(8, 6, 8, 6)
        cg.setHorizontalSpacing(6)
        cg.setVerticalSpacing(2)
        self.continuous_games = QSpinBox()
        self.continuous_games.setRange(1, 9999)
        self.continuous_games.setValue(1)
        self.draw_moves = QCheckBox("Draw after plies")
        self.draw_move_limit = QSpinBox()
        self.draw_move_limit.setRange(1, 9999)
        self.draw_move_limit.setValue(256)
        self.together_notation = QCheckBox("Together notation in one")
        self.after_replacement = QCheckBox("After replacement")
        self.after_replacement.setChecked(True)
        self.do_not_quit_engine = QCheckBox("Do not quit the engine")
        self.write_result_comment = QCheckBox("Write result to comment")
        cg.addWidget(QLabel("Games"), 0, 0)
        cg.addWidget(self.continuous_games, 0, 1)
        cg.addWidget(self.draw_moves, 1, 0)
        cg.addWidget(self.draw_move_limit, 1, 1)
        cg.addWidget(self.together_notation, 2, 0, 1, 2)
        cg.addWidget(self.after_replacement, 3, 0, 1, 2)
        cg.addWidget(self.do_not_quit_engine, 4, 0, 1, 2)
        cg.addWidget(self.write_result_comment, 5, 0, 1, 2)
        left_col.addWidget(self.continuous_box, 1)
        lower.addLayout(left_col, 1)

        settings_box = QGroupBox("Settings")
        sr = QVBoxLayout(settings_box)
        sr.setContentsMargins(8, 6, 8, 6)
        sr.setSpacing(2)
        self.add_thinking_comments = QCheckBox("Add thinking information to comments")
        self.use_piece_sounds = QCheckBox("Use piece sounds")
        self.use_countdown_sounds = QCheckBox("Use countdown sounds")
        self.display_thinking_human = QCheckBox("Display thinking information in playing human.")
        self.dont_lose_time = QCheckBox("Don't lose time")
        self.no_sound_engine_engine = QCheckBox("No sound in engine vs engine")
        self.low_priority = QCheckBox("Low priority")
        for cb in (
            self.add_thinking_comments,
            self.use_piece_sounds,
            self.use_countdown_sounds,
            self.display_thinking_human,
            self.dont_lose_time,
            self.no_sound_engine_engine,
            self.low_priority,
        ):
            sr.addWidget(cb)
        sr.addStretch(1)
        for cb in (
            self.use_piece_sounds,
            self.use_countdown_sounds,
            self.display_thinking_human,
            self.no_sound_engine_engine,
            self.low_priority,
        ):
            cb.setChecked(True)
        lower.addWidget(settings_box, 1)
        root.addLayout(lower, 1)

        # --------------------------------------------------------------
        # Autosave + bottom command buttons.
        # --------------------------------------------------------------
        self.autosave = QGroupBox("AutoSave Notation")
        self.autosave.setCheckable(True)
        self.autosave.setChecked(False)
        al = QHBoxLayout(self.autosave)
        al.setContentsMargins(8, 5, 8, 5)
        al.setSpacing(5)
        self.autosave_path = QLineEdit()
        browse = QPushButton("...")
        browse.setFixedWidth(34)
        browse.clicked.connect(self._browse_autosave)
        al.addWidget(self.autosave_path, 1)
        al.addWidget(browse)
        root.addWidget(self.autosave)

        buttons = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_only_set = QPushButton("Only Set")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_start.setDefault(self._allow_start)
        self.btn_start.setMinimumWidth(88)
        self.btn_only_set.setMinimumWidth(88)
        self.btn_cancel.setMinimumWidth(88)
        self.btn_start.clicked.connect(self._accept_start)
        self.btn_only_set.clicked.connect(self._accept_only_set)
        self.btn_cancel.clicked.connect(self.reject)
        if not self._allow_start:
            self.btn_start.hide()
            self.btn_only_set.setText("OK")
            self.btn_only_set.setDefault(True)
        buttons.addWidget(self.btn_start)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_only_set)
        buttons.addWidget(self.btn_cancel)
        root.addLayout(buttons)

        self._load_saved_setup()

    def _all_player_choices(self) -> List[str]:
        # Human is not an engine; every engine choice comes from Engine list.
        choices = ["Human"]
        for name in _engine_names():
            if name and name not in choices:
                choices.append(name)
        return choices

    def _player_box(self, title: str) -> QGroupBox:
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)
        combo = QComboBox()
        combo.addItems(self._all_player_choices())
        btn_set = QPushButton("Set")
        btn_set.setFixedWidth(46)
        name = QLineEdit()
        grid.addWidget(combo, 0, 0)
        grid.addWidget(btn_set, 0, 1)
        grid.addWidget(QLabel("Name"), 1, 0)
        grid.addWidget(name, 1, 1)
        grid.setColumnStretch(0, 1)
        btn_set.clicked.connect(self._open_engine_list)
        box.player_combo = combo
        box.name_edit = name
        box.btn_set = btn_set
        return box

    def _book_box(self, title: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setCheckable(True)
        box.setChecked(False)
        row = QHBoxLayout(box)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(5)
        combo = QComboBox()
        combo.addItem("No book selected")
        btn = QPushButton("Set")
        btn.setFixedWidth(46)
        row.addWidget(combo, 1)
        row.addWidget(btn)
        box.combo = combo
        box.btn_set = btn
        return box

    def _open_engine_list(self):
        before_cam = self.cam_box.player_combo.currentText()
        before_xanh = self.xanh_box.player_combo.currentText()
        EngineListDialog(self).exec()
        choices = self._all_player_choices()
        for combo, previous in (
            (self.cam_box.player_combo, before_cam),
            (self.xanh_box.player_combo, before_xanh),
        ):
            combo.clear()
            combo.addItems(choices)
            idx = combo.findText(previous)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _swap_players(self):
        a = self.cam_box.player_combo.currentText()
        b = self.xanh_box.player_combo.currentText()
        ai = self.cam_box.player_combo.findText(b)
        bi = self.xanh_box.player_combo.findText(a)
        if ai >= 0:
            self.cam_box.player_combo.setCurrentIndex(ai)
        if bi >= 0:
            self.xanh_box.player_combo.setCurrentIndex(bi)
        an, bn = self.cam_box.name_edit.text(), self.xanh_box.name_edit.text()
        self.cam_box.name_edit.setText(bn)
        self.xanh_box.name_edit.setText(an)

    def _toss_players(self):
        # A toss changes sides without altering the selected participants.
        import random
        if random.getrandbits(1):
            self._swap_players()

    def _browse_autosave(self):
        path = QFileDialog.getExistingDirectory(self, "Select autosave folder")
        if path:
            self.autosave_path.setText(path)

    def _set_combo_text(self, combo: QComboBox, value: str):
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_saved_setup(self):
        s = _settings()
        self._set_combo_text(self.cam_box.player_combo, str(s.value("game/cam_controller", "Human")))
        self._set_combo_text(self.xanh_box.player_combo, str(s.value("game/xanh_controller", "Human")))
        self.cam_box.name_edit.setText(str(s.value("game/cam_name", "")))
        self.xanh_box.name_edit.setText(str(s.value("game/xanh_name", "")))

        self.cam_time.hours.setValue(int(s.value("game/cam_hours", 0)))
        self.cam_time.minutes.setValue(int(s.value("game/cam_minutes", 10)))
        self.cam_time.countdown.setValue(int(s.value("game/cam_countdown", 30)))
        separate = s.value("game/separate_xanh_time", False, type=bool)
        self.separate_xanh_time.setChecked(separate)
        self.xanh_time.hours.setValue(int(s.value("game/xanh_hours", 0)))
        self.xanh_time.minutes.setValue(int(s.value("game/xanh_minutes", 10)))
        self.xanh_time.countdown.setValue(int(s.value("game/xanh_countdown", 30)))

        use_this = s.value("game/start_this_position", False, type=bool)
        self.radio_this.setChecked(use_this)
        self.radio_even.setChecked(not use_this)
        self.continuous_box.setChecked(s.value("game/continuous", False, type=bool))
        self.continuous_games.setValue(int(s.value("game/continuous_games", 1)))
        self.autosave.setChecked(s.value("game/autosave", False, type=bool))
        self.autosave_path.setText(str(s.value("game/autosave_path", "")))

    def _save_setup(self):
        cfg = self.game_config()
        s = _settings()
        for key, value in cfg.items():
            if key.startswith("_ui_"):
                continue
            s.setValue(f"game/{key}", value)
        # Stable keys retained separately for backwards-friendly loading.
        s.setValue("game/cam_controller", cfg["cam_controller"])
        s.setValue("game/xanh_controller", cfg["xanh_controller"])
        s.setValue("game/cam_name", cfg["cam_name"])
        s.setValue("game/xanh_name", cfg["xanh_name"])
        s.setValue("game/cam_hours", cfg["cam_hours"])
        s.setValue("game/cam_minutes", cfg["cam_minutes"])
        s.setValue("game/cam_countdown", cfg["cam_countdown"])
        s.setValue("game/separate_xanh_time", cfg["separate_xanh_time"])
        s.setValue("game/xanh_hours", cfg["xanh_hours"])
        s.setValue("game/xanh_minutes", cfg["xanh_minutes"])
        s.setValue("game/xanh_countdown", cfg["xanh_countdown"])
        s.setValue("game/start_this_position", cfg["start_position"] == "this")
        s.setValue("game/continuous", cfg["continuous"])
        s.setValue("game/continuous_games", cfg["continuous_games"])
        s.setValue("game/autosave", cfg["autosave"])
        s.setValue("game/autosave_path", cfg["autosave_path"])

    def _accept_start(self):
        self.start_requested = True
        self._save_setup()
        self.accept()

    def _accept_only_set(self):
        self.start_requested = False
        self._save_setup()
        self.accept()

    def game_config(self) -> Dict[str, object]:
        """Return a plain configuration dict for MainWindow / Step 3.2."""
        separate = self.separate_xanh_time.isChecked()
        return {
            "cam_controller": self.cam_box.player_combo.currentText(),
            "xanh_controller": self.xanh_box.player_combo.currentText(),
            "cam_name": self.cam_box.name_edit.text().strip(),
            "xanh_name": self.xanh_box.name_edit.text().strip(),
            "cam_hours": self.cam_time.hours.value(),
            "cam_minutes": self.cam_time.minutes.value(),
            "cam_countdown": self.cam_time.countdown.value(),
            "separate_xanh_time": separate,
            "xanh_hours": self.xanh_time.hours.value() if separate else self.cam_time.hours.value(),
            "xanh_minutes": self.xanh_time.minutes.value() if separate else self.cam_time.minutes.value(),
            "xanh_countdown": self.xanh_time.countdown.value() if separate else self.cam_time.countdown.value(),
            "start_position": "this" if self.radio_this.isChecked() else "even",
            "continuous": self.continuous_box.isChecked(),
            "continuous_games": self.continuous_games.value(),
            "draw_moves": self.draw_moves.isChecked(),
            "draw_move_limit": self.draw_move_limit.value(),
            "together_notation": self.together_notation.isChecked(),
            "after_replacement": self.after_replacement.isChecked(),
            "do_not_quit_engine": self.do_not_quit_engine.isChecked(),
            "write_result_comment": self.write_result_comment.isChecked(),
            "add_thinking_comments": self.add_thinking_comments.isChecked(),
            "use_piece_sounds": self.use_piece_sounds.isChecked(),
            "use_countdown_sounds": self.use_countdown_sounds.isChecked(),
            "display_thinking_human": self.display_thinking_human.isChecked(),
            "dont_lose_time": self.dont_lose_time.isChecked(),
            "no_sound_engine_engine": self.no_sound_engine_engine.isChecked(),
            "low_priority": self.low_priority.isChecked(),
            "autosave": self.autosave.isChecked(),
            "autosave_path": self.autosave_path.text().strip(),
        }


class EngineChoiceBox(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Engine settings", parent)
        row = QHBoxLayout(self)
        self.combo = _engine_combo()
        self.btn_set = QPushButton("Set")
        self.btn_add = QPushButton("Add")
        self.btn_set.clicked.connect(self._open_engines)
        self.btn_add.clicked.connect(self._open_engines)
        row.addWidget(self.combo, 1)
        btns = QVBoxLayout(); btns.addWidget(self.btn_set); btns.addWidget(self.btn_add)
        row.addLayout(btns)

    def _open_engines(self):
        EngineListDialog(self).exec()
        current = self.combo.currentText()
        self.combo.clear(); self.combo.addItems(_engine_names() or ["No engine registered"])
        idx = self.combo.findText(current)
        if idx >= 0: self.combo.setCurrentIndex(idx)


class ConsiderSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Consider")
        self.resize(420, 520)
        root = QVBoxLayout(self)
        self.engine_box = EngineChoiceBox()
        root.addWidget(self.engine_box)

        time_box = QGroupBox("Time")
        grid = QGridLayout(time_box)
        self.rb_infinite = QRadioButton("Time infinity"); self.rb_infinite.setChecked(True)
        self.rb_time = QRadioButton("Time")
        self.rb_nodes = QRadioButton("Nodes")
        self.rb_depth = QRadioButton("Depth")
        self.seconds = QSpinBox(); self.seconds.setRange(1, 86400); self.seconds.setValue(60)
        self.nodes = QSpinBox(); self.nodes.setRange(1, 2_000_000_000); self.nodes.setValue(10_000_000)
        self.depth = QSpinBox(); self.depth.setRange(1, 999); self.depth.setValue(20)
        grid.addWidget(self.rb_infinite, 0, 0, 1, 3)
        grid.addWidget(self.rb_time, 1, 0); grid.addWidget(self.seconds, 1, 1); grid.addWidget(QLabel("S"), 1, 2)
        grid.addWidget(self.rb_nodes, 2, 0); grid.addWidget(self.nodes, 2, 1)
        grid.addWidget(self.rb_depth, 3, 0); grid.addWidget(self.depth, 3, 1)
        root.addWidget(time_box)

        set_box = QGroupBox("Set")
        form = QFormLayout(set_box)
        self.candidates = QComboBox(); self.candidates.addItems([str(i) for i in range(1, 11)])
        form.addRow("Candidates", self.candidates)
        form.addRow(QCheckBox("Use Book"))
        form.addRow(QCheckBox("Branch to the top"))
        root.addWidget(set_box, 1)
        root.addWidget(_dialog_buttons(self))


class HintSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hint")
        self.resize(410, 340)
        root = QVBoxLayout(self)
        self.engine_box = EngineChoiceBox()
        self.engine_box.btn_add.hide()
        root.addWidget(self.engine_box)
        settings_box = QGroupBox("Settings")
        row = QHBoxLayout(settings_box)
        row.addWidget(QLabel("Time"))
        self.seconds = QSpinBox(); self.seconds.setRange(1, 3600); self.seconds.setValue(5)
        row.addWidget(self.seconds); row.addWidget(QLabel("S")); row.addStretch(1)
        root.addWidget(settings_box, 1)
        root.addWidget(_dialog_buttons(self))


class MateSettingsDialog(QDialog):
    """Mate settings shell.  No Mate screenshot was supplied, so only common engine/search fields are exposed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mate")
        self.resize(420, 430)
        root = QVBoxLayout(self)
        root.addWidget(EngineChoiceBox())
        search = QGroupBox("Search")
        grid = QGridLayout(search)
        rb_time = QRadioButton("Time"); rb_time.setChecked(True)
        rb_nodes = QRadioButton("Nodes")
        rb_depth = QRadioButton("Depth")
        sec = QSpinBox(); sec.setRange(1, 86400); sec.setValue(30)
        nodes = QSpinBox(); nodes.setRange(1, 2_000_000_000); nodes.setValue(10_000_000)
        depth = QSpinBox(); depth.setRange(1, 999); depth.setValue(30)
        grid.addWidget(rb_time, 0, 0); grid.addWidget(sec, 0, 1); grid.addWidget(QLabel("S"), 0, 2)
        grid.addWidget(rb_nodes, 1, 0); grid.addWidget(nodes, 1, 1)
        grid.addWidget(rb_depth, 2, 0); grid.addWidget(depth, 2, 1)
        root.addWidget(search, 1)
        root.addWidget(_dialog_buttons(self))


class OptionsDialog(QDialog):
    """Options window with the tab structure requested by the user."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Option")
        self.resize(680, 560)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._design_tab(), "Design")
        tabs.addTab(self._font_tab(), "Font")
        tabs.addTab(self._sound_tab(), "Sound")
        tabs.addTab(self._autosave_tab(), "Autosave")
        tabs.addTab(self._language_tab(), "Language")
        tabs.addTab(self._user_tab(), "User")
        root.addWidget(tabs, 1)
        root.addWidget(_dialog_buttons(self))

    def _general_tab(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w)
        recovery = QGroupBox("Startup & Recovery"); form = QFormLayout(recovery)
        self.recovery_choice = QComboBox()
        for label, value in (("Ask every time", "ask"), ("Automatically restore previous session", "restore"), ("Always start a new session", "new")):
            self.recovery_choice.addItem(label, value)
        value = _settings().value("recovery/startup", "ask")
        self.recovery_choice.setCurrentIndex(max(0, self.recovery_choice.findData(value)))
        form.addRow("On interrupted startup", self.recovery_choice); l.addWidget(recovery)
        l.addWidget(QCheckBox("Confirm before resigning"))
        cb = QCheckBox("Restore window layout at startup"); cb.setChecked(True); l.addWidget(cb)
        cb = QCheckBox("Show legal move highlights"); cb.setChecked(True); l.addWidget(cb)
        l.addStretch(1); return w

    def accept(self):
        settings = _settings()
        settings.setValue("recovery/startup", self.recovery_choice.currentData())
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            QMessageBox.warning(self, "Options", "Could not save recovery preference.")
            return
        super().accept()

    def _design_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        theme = QComboBox(); theme.addItems(["System", "Light", "Dark"])
        board = QComboBox(); board.addItems(["Default", "White", "Classic"])
        f.addRow("Theme", theme); f.addRow("Board style", board); return w

    def _font_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        font = QFontComboBox(); size = QSpinBox(); size.setRange(8, 36); size.setValue(10)
        f.addRow("Application font", font); f.addRow("Size", size); return w

    def _sound_tab(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w)
        piece = QCheckBox("Piece sounds"); piece.setChecked(True)
        countdown = QCheckBox("Countdown sounds"); countdown.setChecked(True)
        volume = QSlider(Qt.Orientation.Horizontal); volume.setRange(0, 100); volume.setValue(70)
        l.addWidget(piece); l.addWidget(countdown); l.addWidget(QLabel("Volume")); l.addWidget(volume); l.addStretch(1)
        return w

    def _autosave_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        enabled = QCheckBox("Enable automatic notation save")
        path = QLineEdit()
        browse = QPushButton("Browse...")
        row = QHBoxLayout(); row.addWidget(path, 1); row.addWidget(browse)
        browse.clicked.connect(lambda: self._choose_dir(path))
        interval = QSpinBox(); interval.setRange(1, 3600); interval.setValue(30); interval.setSuffix(" s")
        f.addRow(enabled); f.addRow("Folder", row); f.addRow("Interval", interval); return w

    def _language_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        language = QComboBox(); language.addItems(["English", "Tiếng Việt", "日本語"])
        f.addRow("Language", language); return w

    def _user_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        f.addRow("Name", QLineEdit())
        f.addRow("Rating / Rank", QLineEdit())
        f.addRow("Comment", QLineEdit())
        return w

    def _choose_dir(self, target: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            target.setText(path)
