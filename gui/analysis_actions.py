"""Shared non-playing Analysis/Consider lifecycle over the existing Client."""
import time
from weakref import WeakKeyDictionary
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QPushButton,QComboBox,QSpinBox,QLabel,QMessageBox
from engine import registry
from engine.protocol import export_game,position_id

class AnalysisControls(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(5,3,5,3)
        row=QHBoxLayout();self.engine=QComboBox();self.refresh=QPushButton('Refresh');row.addWidget(self.engine,1);row.addWidget(self.refresh);layout.addLayout(row)
        row=QHBoxLayout();self.start=QPushButton('Start finite analysis');self.stop=QPushButton('Stop');self.stop.setEnabled(False)
        self.limit=QSpinBox();self.limit.setRange(100,86400000);self.limit.setValue(3000);self.limit.setSuffix(' ms (finite)')
        row.addWidget(self.start);row.addWidget(self.stop);row.addWidget(self.limit);layout.addLayout(row)
        self.status=QLabel('DISCONNECTED — Infinite: PENDING_ENGINE_SUPPORT');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.position=QLabel('Position: N/A | Time: N/A | Best line: N/A');self.position.setWordWrap(True);layout.addWidget(self.position)

class AnalysisActions:
    def _init_inspection(self):
        self.analysis_controls=AnalysisControls();self.thinking_information.layout().insertWidget(1,self.analysis_controls)
        self.thinking_information.setMinimumSize(500,300)
        self.thinking_information.table.setMinimumHeight(110)
        self.act_analysis.setText('Analysis (finite)...')
        self._evaluation_nodes=WeakKeyDictionary();self._pending_graph=False;self._live_evaluation_node=None
        self._inspection_error=''
        self._inspection_mode=None;self._desired_inspection=None;self._inspection_restart=False;self._inspection_valid=False;self._inspection_position=None;self._inspection_pid='';self._inspection_best='';self._inspection_started_at=None
        self.analysis_controls.start.clicked.connect(lambda:self._start_inspection('analysis'))
        self.analysis_controls.stop.clicked.connect(self._stop_inspection);self.analysis_controls.refresh.clicked.connect(self._refresh_analysis_engines)
        self.engine_controller.stateChanged.connect(self._inspection_state)
        self._inspection_timer=QTimer(self);self._inspection_timer.setInterval(200);self._inspection_timer.timeout.connect(self._inspection_tick);self._inspection_timer.timeout.connect(self._flush_evaluations);self._inspection_timer.start()
        self._refresh_analysis_engines()

    def _refresh_analysis_engines(self):
        combo=self.analysis_controls.engine;selected=combo.currentData() or registry.settings().value('analysis/engine_id','')
        combo.blockSignals(True);combo.clear()
        for entry in registry.load():
            if registry.playable(entry):combo.addItem(entry['name'],entry.get('id',entry['path']))
        index=combo.findData(selected);combo.setCurrentIndex(index if index>=0 else 0);combo.blockSignals(False)
        if hasattr(self,'candidate_count'):
            self._consider_selected_engine();self.consider_start.setEnabled(combo.count()>0)
        self.analysis_controls.start.setEnabled(combo.count()>0 and not self.engine_controller.running)

    def _inspection_key(self):
        from engine.game import _position_hash
        return (id(self.game),id(self.game.current_node),_position_hash(self.game.board,self.game.current))

    def _start_inspection(self,mode='analysis'):
        if self.is_game_active:
            self.statusBar().showMessage('Stop the game before starting Analysis/Consider.',6000);return False
        self._desired_inspection=mode
        if self.engine_controller.running:
            if self._engine_mode=='play':self._desired_inspection=None;return False
            self._inspection_restart=True;self._inspection_valid=False;self.engine_controller.stop();return True
        self._refresh_analysis_engines();chosen=self.analysis_controls.engine.currentData()
        entry=next((e for e in registry.load() if e.get('id',e['path'])==chosen and registry.playable(e)),None)
        if not entry:
            self._desired_inspection=None
            self.analysis_controls.status.setText('Engine unavailable. Use Tools → Engine settings → Add/Verify, then Refresh.')
            QMessageBox.warning(self,'Engine unavailable','Select and verify a CLP-EP v1 executable in Tools → Engine settings. Local rules and file operations remain available.')
            return False
        try:
            state=export_game(self.game)
            self.engine_controller.set_engine_path(entry['path'],entry.get('args',[]),entry.get('options',{}))
        except (ValueError,RuntimeError,KeyError) as exc:
            self._desired_inspection=None;QMessageBox.warning(self,'Analysis unavailable',str(exc));return False
        if mode=='consider':
            if 'MultiPV' in entry.get('option_definitions',{}):self.engine_controller.options['MultiPV']=self.candidate_count.value()
            self.engine_dock.show();self.consider_dock.show();self.consider_dock.raise_()
        else:
            self.engine_dock.show();self.thinking_dock.show();self.thinking_dock.raise_()
        self._inspection_error='';self._live_evaluation_node=None
        settings=registry.settings();settings.setValue('analysis/engine_id',chosen);settings.sync()
        self._inspection_mode=mode;self._engine_mode=mode;self._inspection_restart=False;self._inspection_valid=True
        self._inspection_position=self._inspection_key();self._inspection_pid=position_id(state);self._inspection_best='';self._engine_bestmove_text='';self._inspection_started_at=None
        self.clear_thinking_information();self._clear_candidates();self.win_percentage.reset()
        self.analysis_controls.position.setText('Position '+self._inspection_pid[:12]+' | Time: N/A | Best line: N/A')
        self.analysis_controls.start.setEnabled(False);self.analysis_controls.stop.setEnabled(True);self.analysis_controls.engine.setEnabled(False)
        # v1 has no infinite grammar. This is ONE explicitly finite request.
        if not self.engine_controller.start_search(self.game,(self.consider_limit.value() if mode=='consider' else self.analysis_controls.limit.value())):
            self._inspection_finished(1);return False
        return True

    def _on_analysis(self):
        if self._inspection_mode=='analysis' and self.engine_controller.running:self._stop_inspection()
        else:self._start_inspection('analysis')

    def _stop_inspection(self):
        self._desired_inspection=None;self._inspection_restart=False;self._inspection_valid=False
        if self.engine_controller.running:self.engine_controller.stop()
        else:self._inspection_finished(0)

    def _inspection_state(self,state):
        if self._inspection_mode:
            self.analysis_controls.status.setText(f'{state} — {self._inspection_mode}, finite | Infinite: PENDING_ENGINE_SUPPORT')
            if hasattr(self,'consider_stop'):
                self.consider_status.setText(state+' | '+getattr(self,'_consider_capability_text','MultiPV: N/A'))
                self.consider_stop.setEnabled(state in ('CONNECTING','SEARCHING','STOPPING'));self.candidate_count.setEnabled(False)
            self.act_analysis.setText('Stop Analysis' if state in ('CONNECTING','SEARCHING','STOPPING') and self._inspection_mode=='analysis' else 'Analysis (finite)...')

    def _inspection_started(self):
        self._inspection_started_at=time.monotonic();self._inspection_state('SEARCHING')

    def _inspection_tick(self):
        if self._inspection_started_at is not None and self.engine_controller.running:
            elapsed=int((time.monotonic()-self._inspection_started_at)*1000)
            self.analysis_controls.position.setText(f'Position {self._inspection_pid[:12]} | Time: {elapsed} ms | Best line: {self._inspection_best or "N/A"}')
        self._inspection_position_changed()

    def _inspection_position_changed(self):
        if not getattr(self,'_inspection_mode',None):return
        if self.is_game_active:self._stop_inspection();return
        if self._inspection_position!=self._inspection_key() and self._desired_inspection:
            self._inspection_valid=False;self._inspection_restart=True
            self.clear_thinking_information();self._clear_candidates()
            if self.engine_controller.running:self.engine_controller.stop()
            else:QTimer.singleShot(0,self._finish_inspection_transition)

    def _accept_inspection_info(self,info):
        return self._inspection_valid and self._inspection_position==self._inspection_key() and info.position_id==self._inspection_pid

    def _inspection_info(self,info):
        if not self._accept_inspection_info(info):return
        if info.multipv==1:self._inspection_best=' '.join(info.pv or [])
        self.thinking_information.update_info(info)
        self._update_candidates(info)
        if info.multipv==1 and info.score is not None and info.score_kind=='cp' and info.score_perspective=='root' and info.root_side in ('CAM','XANH') and info.bound=='exact':
            self._evaluation_nodes[self.game.current_node]=(info.position_id,info.score if info.root_side=='CAM' else -info.score)
            self._pending_graph=True;self._live_evaluation_node=self.game.current_node
        self._inspection_tick()

    def _flush_evaluations(self):
        if getattr(self,'_pending_graph',False):
            self._pending_graph=False;self._update_history_and_graph()

    def _inspection_bestmove(self,move,text):
        if not self._inspection_valid or self._inspection_position!=self._inspection_key():return
        if text:self._inspection_best=text;self._engine_bestmove_text=text
        self._inspection_tick()

    def _inspection_finished(self,code):
        # Defer until any currently executing position-changing GUI action finishes.
        QTimer.singleShot(0,self._finish_inspection_transition)

    def _finish_inspection_transition(self):
        if self._closing:return
        if self.engine_controller.running:return
        self._flush_evaluations()
        mode=self._desired_inspection
        restart=self._inspection_restart and mode is not None and not self.is_game_active
        self._inspection_mode=None;self._engine_mode='idle';self._inspection_valid=False;self._inspection_restart=False;self._desired_inspection=None
        self._live_evaluation_node=None;self._update_history_and_graph()
        self.analysis_controls.stop.setEnabled(False);self.analysis_controls.engine.setEnabled(True);self._refresh_analysis_engines()
        self.act_analysis.setText('Analysis (finite)...')
        self.analysis_controls.status.setText(('ERROR: '+self._inspection_error) if self._inspection_error else 'Finished / stopped (finite). Infinite: PENDING_ENGINE_SUPPORT')
        if hasattr(self,'consider_stop'):
            self.consider_stop.setEnabled(False);self._consider_selected_engine()
        if restart:self._start_inspection(mode)

    def _clear_candidates(self):
        pass  # STEP 6C attaches the existing Consider panel here.
