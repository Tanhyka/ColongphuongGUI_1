"""Versioned, atomic settings-backed Qt layout; independent of game recovery."""
import json,base64
from PyQt6.QtCore import QTimer,QByteArray,QRect
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QDockWidget
from engine import registry

VERSION=5

def encoded(value):return bytes(value.toBase64()).decode('ascii')
def decoded(value):return QByteArray(base64.b64decode(value,validate=True))

class LayoutActions:
    def _init_layout(self):
        self._last_layout=None;self._layout_busy=False
        raw=registry.settings().value('workspace/layout_v5','')
        if raw:
            try:
                if not self._apply_layout(json.loads(raw)):raise ValueError('Unsupported or invalid Qt layout')
            except (ValueError,TypeError,KeyError):
                self._default_docks();self.statusBar().showMessage('Saved layout is invalid or outdated. Default workspace restored.',10000)
        self._layout_timer=QTimer(self);self._layout_timer.setInterval(750)
        self._layout_timer.timeout.connect(self._save_layout);self._layout_timer.start()
        QTimer.singleShot(0,self._ensure_windows_on_screen)

    def _layout_snapshot(self):
        return dict(version=VERSION,geometry=encoded(self.saveGeometry()),state=encoded(self.saveState(VERSION)),engine=encoded(self.engine_workspace.saveState(VERSION)))

    def _apply_layout(self,data):
        if not isinstance(data,dict) or data.get('version')!=VERSION:return False
        # Decode everything before changing the live layout.
        geometry,state,engine=(decoded(data[k]) for k in ('geometry','state','engine'))
        if not geometry or not state or not engine:return False
        self._layout_busy=True
        try:
            if not self.restoreState(state,VERSION) or not self.engine_workspace.restoreState(engine,VERSION):return False
            if not self.restoreGeometry(geometry):return False
            self._ensure_windows_on_screen();self._schedule_cluster_update()
            return True
        finally:self._layout_busy=False

    def _save_layout(self,explicit=False):
        if getattr(self,'_review_active',False):return
        if getattr(self,'_layout_busy',False):return
        data=self._layout_snapshot();raw=json.dumps(data,sort_keys=True)
        if explicit or raw!=self._last_layout:
            settings=registry.settings();settings.setValue('workspace/layout_v5',raw);settings.sync()
            if settings.status()!=settings.Status.NoError:
                self.statusBar().showMessage('Could not save workspace layout. Check the preferences folder.',8000);return
            self._last_layout=raw
        if explicit:self.statusBar().showMessage('Layout saved',4000)

    def _reset_layout(self):
        self._leave_review()
        self._layout_busy=True
        try:self._default_docks();self._ensure_windows_on_screen()
        finally:self._layout_busy=False
        self._save_layout(explicit=True)

    def _ensure_windows_on_screen(self):
        screens=[s.availableGeometry() for s in QGuiApplication.screens()]
        if not screens:return
        for window in [self]+[d for d in self.workspace_docks+self.engine_docks if d.isFloating()]:
            frame=window.frameGeometry()
            # Require a usable titlebar on a live screen, not merely a corner.
            title=QRect(frame.x(),frame.y(),max(100,frame.width()),30)
            if any(s.intersected(title).width()>=100 and s.intersected(title).height()>=20 for s in screens):continue
            target=screens[0]
            window.resize(min(window.width(),target.width()),min(window.height(),target.height()))
            window.move(target.x()+20,target.y()+20)

    def _show_workspace_panel(self,dock,checked):
        dock.setVisible(checked)
        if checked:
            if dock in self.engine_docks:self.engine_dock.show()
            self._ensure_windows_on_screen();dock.raise_();dock.activateWindow()
