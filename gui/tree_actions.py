"""Annotation and branch commands on the existing game model."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QMessageBox, QInputDialog, QLabel
from PyQt6.QtGui import QAction, QKeySequence
from engine.session import encode_game, decode_game
from engine.tree_record import GLYPHS


class TreeActions:
    def _init_tree_actions(self):
        self._tree_undo = []
        self._force_variation = False
        self.variation_indicator = QLabel('')
        self.statusBar().addPermanentWidget(self.variation_indicator)
        self.notation_view.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notation_view.tree.customContextMenuRequested.connect(self._tree_context)

    def _tree_context(self, pos):
        item = self.notation_view.tree.itemAt(pos)
        if item is None:return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node is None:return
        menu = self._tree_menu(node)
        menu.exec(self.notation_view.tree.viewport().mapToGlobal(pos))

    def _tree_menu(self, node):
        menu = QMenu(self)
        variation = False;ancestor = node
        while ancestor.parent is not None:
            variation |= ancestor.parent.children[0] is not ancestor
            ancestor = ancestor.parent
        if node.parent is not None:
            if variation:menu.addAction('Make mainline', lambda: self._tree_edit('promote',node))
            menu.addAction('Delete from here', lambda: self._tree_delete(node))
        menu.addAction('Comment on this move', lambda: self._tree_comment(node))
        glyphs = menu.addMenu('Annotate with glyphs')
        for glyph in GLYPHS:
            action = glyphs.addAction(glyph)
            action.setCheckable(True);action.setChecked(glyph in node.glyphs)
            action.triggered.connect(lambda checked,g=glyph: self._tree_edit('glyph',node,g))
        glyphs.addAction('Clear glyphs',lambda:self._tree_edit('clear_glyphs',node))
        if not variation:
            action=menu.addAction('Force variation')
            action.setCheckable(True);action.setChecked(self._force_variation)
            action.triggered.connect(lambda checked:self._set_force_variation(node,checked))
        for action in menu.actions():action.setEnabled(not self.is_game_active and not getattr(self,'_review_active',False))
        return menu

    def _set_force_variation(self, node, enabled):
        if self.is_game_active or getattr(self,'_review_active',False):return
        self._force_variation = enabled
        self.variation_indicator.setText('FORCE VARIATION - enter an alternative move' if enabled else '')
        if enabled:
            self._on_node_selected(node.parent or node)
            self.board.set_moves_enabled(True)

    def _tree_delete(self, node):
        if QMessageBox.question(self,'Delete variation','Delete this move and all its descendants? Other branches will be retained.',
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self._tree_edit('delete',node)

    def _tree_comment(self, node):
        text, accepted = QInputDialog.getMultiLineText(self,'Move comment','Plain text comment (empty to remove):',node.comment)
        if accepted:self._tree_edit('comment',node,text)

    def _tree_edit(self, operation, node, value=None):
        if self.is_game_active or getattr(self,'_review_active',False) or not self.game.contains_node(node):return
        before = encode_game(self.game)
        if operation == 'delete':self.game.delete_branch(node)
        elif operation == 'promote':self.game.promote(node)
        elif operation == 'comment':node.comment = value
        elif operation == 'clear_glyphs':node.glyphs = []
        elif operation == 'glyph':
            if value not in GLYPHS:raise ValueError('Unsupported glyph')
            node.glyphs = [g for g in node.glyphs if g != value] if value in node.glyphs else node.glyphs + [value]
        else:raise ValueError('Unsupported tree edit')
        self._tree_undo.append((self.game.game_id,before));self._tree_undo=self._tree_undo[-10:]
        self._tree_changed()

    def _tree_changed(self):
        self._document_dirty = True
        self.notation_view.rebuild_tree(self.game.root,self.game.current_node,self.game.board,
                                       game_result=self.game.result,current_player=self.game.current)
        self.board.reset_transient_state(clear_last_move=True)
        self._update_history_and_graph();self._update_menu_states();self._sync_all()

    def _undo_tree_edit(self):
        if self.is_game_active or getattr(self,'_review_active',False):return
        if not self._tree_undo or self._tree_undo[-1][0]!=self.game.game_id:
            self.statusBar().showMessage('No tree edit to undo in this game.',4000);return
        _,payload = self._tree_undo.pop()
        self.game = decode_game(payload);self.board.game = self.game
        self._tree_changed()
