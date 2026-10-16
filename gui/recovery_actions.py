"""Recovery dialogs and workspace integration; storage belongs to engine.session."""
import json
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication,QMessageBox,QCheckBox
from engine.session import SessionStore,encode_game,decode_game
from engine.notation import _base_position_payload
from engine.pieces import Player
from engine import registry

class RecoveryActions:
    def _init_recovery(self):
        self._session_store=SessionStore();self._session_ready=False;self._last_session=None
        self._session_timer=QTimer(self);self._session_timer.setInterval(1000);self._session_timer.timeout.connect(self._save_session)
        QTimer.singleShot(0,self._startup_recovery)

    def _choose_recovery(self):
        box=QMessageBox(self);box.setWindowTitle('Restore Previous Session')
        box.setText('An unfinished session was found. Would you like to restore your previous game and workspace?')
        restore=box.addButton('Restore',QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Start New',QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restore)
        remember=QCheckBox("Remember my choice and don't ask again",box);box.setCheckBox(remember)
        box.exec();choice='restore' if box.clickedButton()==restore else 'new'
        if remember.isChecked():
            settings=registry.settings();settings.setValue('recovery/startup',choice);settings.sync()
        return choice

    def _startup_recovery(self):
        try:
            previous=self._session_store.interrupted()
            if previous:
                choice=registry.settings().value('recovery/startup','ask')
                if choice not in ('restore','new'):choice=self._choose_recovery()
                if choice=='restore':self._restore_session(previous)
            if self._session_store.errors:
                self.statusBar().showMessage('Recovery: invalid snapshot ignored; valid backup used when available. '+self._session_store.errors[-1],15000)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            QMessageBox.warning(self,'Recovery unavailable',str(exc))
        self._session_ready=True;self._save_session();self._session_timer.start()

    def _workspace_snapshot(self):
        workspace=dict(flipped=self.board.is_flipped,source=self.current_file_path,dirty=getattr(self,'_document_dirty',False),setup=self.game_setup_config,
                       moves_enabled=self.board.moves_enabled,geometry=bytes(self.saveGeometry().toBase64()).decode(),
                       player_cam=self.card_cam.player_name,player_xanh=self.card_xanh.player_name,
                       record_metadata=getattr(self,'record_metadata',{}),editor=None,
                       views={name:getattr(self,name).isChecked() for name in ('act_view_toolbar','act_view_graph','act_view_coords','act_view_notation','act_view_winrate','act_view_thinking')},
                       splitters={name:getattr(self,name).sizes() for name in ('top_splitter','bottom_splitter','analysis_splitter') if hasattr(self,name)})
        workspace['training_review']=self._review_workspace_snapshot()
        editor=QApplication.activeModalWidget()
        if hasattr(editor,'editor_game'):
            side=Player.CAM if editor.radio_cam.isChecked() else Player.XANH
            workspace['editor']=dict(position=_base_position_payload(editor.editor_game.board,side),flipped=editor.board_canvas.is_flipped,
                                     tool=editor.board_canvas.tool_mode,selected=editor.board_canvas.selected_cell,
                                     palette=[editor.board_canvas.palette_piece[0].name,editor.board_canvas.palette_piece[1].name] if editor.board_canvas.palette_piece else None,
                                     hand=[editor.board_canvas.hand_piece[0].name,editor.board_canvas.hand_piece[1].name] if editor.board_canvas.hand_piece else None,
                                     team=editor.board_canvas.team_mode)
        # Autosave does not claim to resume live clocks or external search.
        return workspace

    def _save_session(self,clean=False):
        if not getattr(self,'_session_ready',False):return
        try:
            meta=getattr(self,'record_metadata',{})
            if meta.get('signature'):
                from engine.records import history_signature
                if history_signature(self.game)!=meta['signature']:self._document_dirty=True
            workspace=self._workspace_snapshot()
            signature=json.dumps([encode_game(self.game),workspace],sort_keys=True,ensure_ascii=False)
            if clean or signature!=self._last_session:
                self._session_store.save(self.game,workspace,clean=clean);self._last_session=signature
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.statusBar().showMessage(f'Session autosave failed: {exc}',10000)

    def _restore_session(self,payload):
        # Construct and validate replacement before touching current state.
        game=decode_game(payload['game']);ws=payload['workspace']
        if ws.get('training_review') is not None:
            from engine.review import validate_workspace
            validate_workspace(ws['training_review'])
        self._leave_review()
        self._stop_match_runtime(clear_cards=False)
        self._tree_undo.clear()
        self._set_force_variation(self.game.current_node,False)
        self.game=game;self.board.game=game
        self.current_file_path=ws.get('source');self._document_dirty=ws.get('dirty',False)
        self.record_metadata=ws.get('record_metadata',{});self.game_setup_config=ws.get('setup',{})
        self.card_cam.set_player_name(ws.get('player_cam') or 'Cam');self.card_xanh.set_player_name(ws.get('player_xanh') or 'Xanh')
        if self.board.is_flipped!=bool(ws.get('flipped')):self._on_turn_board()
        self.board.reset_transient_state();self.board._clear_annotations();self.board.set_moves_enabled(ws.get('moves_enabled',True))
        if ws.get('geometry') and not hasattr(self,'workspace_docks'):
            from PyQt6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(ws['geometry'].encode()))
        for name,value in ws.get('views',{}).items():
            if name in ('act_view_toolbar','act_view_coords','act_view_winrate'):
                getattr(self,name).setChecked(bool(value))
        for name,sizes in ws.get('splitters',{}).items():
            if name in ('top_splitter','bottom_splitter','analysis_splitter') and hasattr(self,name):
                getattr(self,name).setSizes(sizes)
        self._restore_review_workspace(ws.get('training_review'))
        self.notation_view.rebuild_tree(game.root,game.current_node,game.board,game_result=game.result,current_player=game.current)
        self._update_history_and_graph();self._update_menu_states();self._sync_all()
        self.statusBar().showMessage('Previous session restored. Any engine analysis must be restarted explicitly.',12000)
        if ws.get('editor'):
            self._recovery_editor=ws['editor'];QTimer.singleShot(0,self._on_edit_position)

    def _recover_previous_session(self):
        try:
            payload=self._session_store.recoverable()
            if not payload:raise ValueError('No valid previous session is available.')
            self._restore_session(payload);self._save_session()
        except (OSError,ValueError,KeyError,TypeError) as exc:QMessageBox.warning(self,'Recover Previous Session',str(exc))
