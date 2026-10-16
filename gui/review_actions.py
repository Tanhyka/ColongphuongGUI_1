"""Review workspace shares the existing board, rules and notation tree."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPlainTextEdit,QMessageBox,QFileDialog
from gui.training_review import ReviewPanel


class ReviewActions:
    def _init_review(self):
        self._review_active=False;self._review_loading=False
        self._review_records=[];self._review_drafts={};self._review_key=None
        self.review_panel=ReviewPanel(self)
        self.review_dock=self._new_dock(self,'training_review','Training Review',self.review_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.review_dock);self.review_dock.hide()
        self.review_details=QPlainTextEdit();self.review_details.setReadOnly(True);self.review_details.setMaximumHeight(200)
        self.notation_view.layout().addWidget(self.review_details);self.review_details.hide()
        self.review_panel.commit.connect(self._record_review)
        self.review_panel.open_review.connect(self._open_selected_review)
        self.review_panel.save_requested.connect(self._save_reviews_file)
        self.review_panel.load_requested.connect(self._load_reviews_file)
        self.review_panel.changed.connect(self._review_capture)
        self.review_panel.leave_requested.connect(self._leave_review)
        self.review_dock.visibilityChanged.connect(self._review_visibility)

    def _review_visibility(self, visible):
        if not visible and self._review_active:self._leave_review()

    def _enter_review(self):
        if self._review_active:
            self.review_dock.show();self.review_dock.raise_();return
        if self.is_game_active:
            self.statusBar().showMessage('Stop the active game before Training Review.',6000);return
        self._review_return=dict(layout=self._layout_snapshot(),game=self.game,node=self.game.current_node,
                                 moves=self.board.moves_enabled,force=self._force_variation)
        self._set_force_variation(self.game.current_node,False)
        self._review_active=True
        self._stop_inspection()
        for dock in self.workspace_docks+self.engine_docks:dock.hide()
        self.board_dock.setFloating(False);self.notation_dock.setFloating(False)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.review_dock)
        self.splitDockWidget(self.review_dock,self.board_dock,Qt.Orientation.Horizontal)
        self.splitDockWidget(self.board_dock,self.notation_dock,Qt.Orientation.Horizontal)
        self.review_dock.show();self.board_dock.show();self.notation_dock.show();self.review_details.show()
        self.board.set_moves_enabled(False)
        self.resizeDocks([self.review_dock,self.board_dock,self.notation_dock],[260,700,320],Qt.Orientation.Horizontal)
        self._review_position_changed()

    def _leave_review(self):
        if not self._review_active:return
        self._review_capture();self._review_active=False
        saved=self._review_return
        self.review_dock.hide();self.review_details.hide()
        try:
            if not self._apply_layout(saved['layout']):self._default_docks()
        except (ValueError,KeyError,TypeError):self._default_docks()
        if self.game is saved['game'] and self.game.contains_node(saved['node']):
            self._on_node_selected(saved['node']);self.board.set_moves_enabled(saved['moves'])
            self._force_variation=saved['force']
            self.variation_indicator.setText('FORCE VARIATION - enter an alternative move' if saved['force'] else '')
        self._review_key=None;self._schedule_cluster_update()

    def _review_capture(self):
        if self._review_loading or not self._review_key:return
        from engine.review import make_review
        values=self.review_panel.values()
        old=self._review_drafts.get(self._review_key)
        # Called before navigation changes the panel; bind to its original node.
        game=self._review_return['game']
        selected=game.current_node
        node_id=self._review_key[len(game.game_id)+1:]
        node=next((n for n in game.nodes() if n.node_id==node_id),None)
        if node is None:return
        if old is None or any(old[k]!=v for k,v in values.items()):
            try:
                game.go_to_node(node)
                self._review_drafts[self._review_key]=make_review(game,values,self.current_file_path)
            finally:game.go_to_node(selected)
        self._save_session()

    def _review_position_changed(self):
        if not getattr(self,'_review_active',False):return
        if self.game is not self._review_return['game']:
            self._leave_review();return
        key=self.game.game_id+':'+self.game.current_node.node_id
        if key!=self._review_key:
            self._review_capture();self._review_key=key;self._review_loading=True
            try:self.review_panel.set_values(self._review_drafts.get(key,{}))
            finally:self._review_loading=False
        node=self.game.current_node
        source=self.current_file_path or 'Unsaved current game'
        self.review_panel.identity.setText('Source: '+source+'\nNode: '+node.node_id+'\nSide: '+self.game.current.name)
        lines=['Current: '+(node.notation_text or 'Start position'),'Node: '+node.node_id,'Annotations: '+' '.join(node.glyphs),node.comment,'','Candidates / defense branches:']
        lines.extend(('Main: ' if i==0 else 'Variation: ')+c.notation_text+' ['+c.node_id+']' for i,c in enumerate(node.children))
        self.review_details.setPlainText('\n'.join(lines))
        self.review_panel.progress.setText(f'{len(self._review_records)} reviews; {len(self._review_drafts)} position drafts')
        combo=self.review_panel.review_selector;selected=combo.currentData();combo.blockSignals(True);combo.clear()
        for r in self._review_records:
            combo.addItem(r['judgement']+' '+r['node_id'][:8]+' '+r['review_id'][:8],r['review_id'])
        index=combo.findData(selected)
        if index>=0:combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self.board.set_moves_enabled(False)

    def _record_review(self):
        if not self._review_active:return
        from engine.review import make_review
        try:
            self._review_capture()
            record=self._review_drafts[self._review_key]
            if not any(r['review_id']==record['review_id'] for r in self._review_records):self._review_records.append(record)
            self._review_position_changed();self._save_session()
            self.statusBar().showMessage('Human observation recorded; no correctness or mate proof implied.',6000)
        except (ValueError,KeyError,TypeError) as exc:QMessageBox.warning(self,'Training Review',str(exc))

    def _save_reviews_file(self):
        from engine.review import save_reviews
        from engine.session import data_dir
        from pathlib import Path
        path,_=QFileDialog.getSaveFileName(self,'Save Human Reviews',str(data_dir()/'reviews.jsonl'),'Review JSONL (*.jsonl)')
        if not path:return
        try:
            if self.current_file_path and Path(path).resolve()==Path(self.current_file_path).resolve():raise ValueError('Review output must be separate from the game record')
            self._review_capture()
            merged={r['review_id']:r for r in self._review_records}
            merged.update((r['review_id'],r) for r in self._review_drafts.values())
            save_reviews(path,list(merged.values()))
            self.statusBar().showMessage('Reviews and position drafts saved as separate JSONL.',6000)
        except (OSError,ValueError,KeyError,TypeError) as exc:QMessageBox.warning(self,'Save Human Reviews',str(exc))

    def _load_reviews_file(self):
        from engine.review import load_reviews
        from engine.session import data_dir
        from pathlib import Path
        path,_=QFileDialog.getOpenFileName(self,'Load Human Reviews',str(data_dir()),'Review JSONL (*.jsonl)')
        if not path:return
        try:
            loaded=load_reviews(Path(path).read_text(encoding='utf-8-sig'))
            merged={r['review_id']:r for r in self._review_records}
            for r in loaded:
                if r['review_id'] in merged and merged[r['review_id']]!=r:raise ValueError('Conflicting review identity; existing data retained')
                merged[r['review_id']]=r
            self._review_records=list(merged.values());self._review_position_changed();self._save_session()
            self.statusBar().showMessage('Reviews loaded; identities checked. Existing drafts retained.',6000)
        except (OSError,ValueError,KeyError,TypeError) as exc:QMessageBox.warning(self,'Load Human Reviews',str(exc))

    def _open_selected_review(self):
        from engine.review import position_identity
        selected=self.review_panel.review_selector.currentData()
        record=next((r for r in self._review_records if r['review_id']==selected),None)
        if record is None:return
        node=next((n for n in self.game.nodes() if n.node_id==record['node_id']),None)
        if self.game.game_id!=record['game_id'] or node is None:
            self.statusBar().showMessage('This review belongs to another game. Open its source LPGF first.',8000);return
        before=self.game.current_node;self.game.go_to_node(node)
        matches=position_identity(self.game)==record['position_id'] and self.game.current.name==record['side']
        self.game.go_to_node(before)
        if not matches:
            self.statusBar().showMessage('Position identity mismatch; review was not applied.',8000);return
        self._review_capture()
        self._on_node_selected(node)
        self._review_drafts[self._review_key]=record
        self.review_panel.set_values(record);self._save_session()

    def _review_workspace_snapshot(self):
        saved=getattr(self,'_review_return',{})
        return dict(schema='clp.review-workspace/1',records=self._review_records,drafts=self._review_drafts,
                    active=self._review_active,return_node=saved['node'].node_id if self._review_active else None,
                    return_moves=bool(saved.get('moves',False)),return_layout=saved.get('layout') if self._review_active else None)

    def _restore_review_workspace(self,value):
        if value is None:return
        from engine.review import validate_workspace
        from PyQt6.QtCore import QTimer
        validate_workspace(value)
        self._review_records=value['records'];self._review_drafts=value['drafts']
        if value['active']:
            def reopen():
                self._enter_review()
                self._review_return['node']=next((n for n in self.game.nodes() if n.node_id==value['return_node']),self.game.root)
                self._review_return['moves']=value['return_moves']
                if value['return_layout']:self._review_return['layout']=value['return_layout']
            QTimer.singleShot(0,reopen)
