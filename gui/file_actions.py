"""Native file/clipboard/image dialogs backed by the bundled engine codecs."""
from pathlib import Path
from PyQt6.QtWidgets import QFileDialog,QMessageBox,QApplication
from engine.game import Game
from engine.lppn import from_lppn,to_lppn
from engine.records import load_record,write_record,history_signature
from gui.constants import DEFAULT_KYPHO_DIR

class FileActions:
    def _install_position_game(self,game,*,editable=True):
        self._leave_review()
        self._tree_undo.clear()
        self._set_force_variation(self.game.current_node,False)
        self._stop_match_runtime(clear_cards=True)
        self.game=game;self.board.game=game;self.is_game_active=False
        self.board._clear_annotations();self.board.reset_transient_state();self.board.set_moves_enabled(editable)
        self.notation_view.rebuild_tree(game.root,game.current_node,game.board,game_result=game.result,current_player=game.current)
        self._update_history_and_graph();self._update_menu_states();self._sync_all()

    def _open_record(self,kind=None):
        self._ensure_default_dir()
        filters={'txt':'TXT Record (*.txt)','lpgf':'LPGF Record (*.lpgf)'}
        path,_=QFileDialog.getOpenFileName(self,'Open Record',DEFAULT_KYPHO_DIR,filters.get(kind,'Record Files (*.txt *.lpgf)')+';;All Files (*)')
        if not path:return
        try:
            data=Path(path).read_bytes()
            for encoding in ('utf-8-sig','cp1258'):
                try:content=data.decode(encoding);break
                except UnicodeDecodeError:continue
            else:raise ValueError('Cannot decode record as UTF-8 or Windows Vietnamese text.')
            game,meta=load_record(content,path)  # failure leaves live board untouched
            self.record_metadata=meta;self.current_file_path=path;self._document_dirty=False
            self.card_cam.set_player_name(meta.get('player_cam') or 'Cam');self.card_xanh.set_player_name(meta.get('player_xanh') or 'Xanh')
            self._install_position_game(game,editable=False)
            self.setWindowTitle('ColongphuongGUI - '+Path(path).name)
        except (OSError,ValueError,TypeError,KeyError,IndexError) as exc:QMessageBox.critical(self,'Open Record',f'Could not open {Path(path).name}:\n{exc}')

    def _write_record_file(self,path,*,adopt=True):
        try:
            text=write_record(path,self.game,self.record_metadata,player_cam=self.card_cam.player_name or 'Cam',player_xanh=self.card_xanh.player_name or 'Xanh')
            if adopt:
                self.current_file_path=path;self._document_dirty=False
                self.record_metadata.update(original_text=text,original_format='lpgf',signature=history_signature(self.game))
                self.setWindowTitle('ColongphuongGUI - '+Path(path).name)
            self._save_session();self.statusBar().showMessage('Record saved: '+path,6000)
        except (OSError,ValueError,TypeError,KeyError) as exc:QMessageBox.critical(self,'Save Record',str(exc))

    def _export_lpgf(self):
        self._ensure_default_dir();path,_=QFileDialog.getSaveFileName(self,'Export LPGF',DEFAULT_KYPHO_DIR,'LPGF Record (*.lpgf)')
        if path:self._write_record_file(path if path.lower().endswith('.lpgf') else path+'.lpgf',adopt=False)

    def _current_lppn(self):
        node=self.game.current_node;ply=getattr(self.game,'base_ply',0)
        while node.parent is not None:ply+=1;node=node.parent
        return to_lppn(self.game.board,self.game.current,ply=ply)

    def _import_lppn_text(self,text):
        position=from_lppn(text);game=Game();game.set_base_position(position.board,position.turn);game.base_ply=position.ply
        self.current_file_path=None;self.record_metadata={};self._document_dirty=True
        self._install_position_game(game);self.set_bottom_player(position.turn);self._save_session()
        self.setWindowTitle('ColongphuongGUI - LPPN Position')

    def _open_lppn(self):
        self._ensure_default_dir();path,_=QFileDialog.getOpenFileName(self,'Import LPPN',DEFAULT_KYPHO_DIR,'LPPN Position (*.lppn *.txt);;All Files (*)')
        if path:
            try:self._import_lppn_text(Path(path).read_text(encoding='utf-8-sig'))
            except (OSError,ValueError) as exc:QMessageBox.critical(self,'Import LPPN',str(exc))

    def _paste_lppn(self):
        try:self._import_lppn_text(QApplication.clipboard().text())
        except ValueError as exc:QMessageBox.critical(self,'Paste LPPN',str(exc))

    def _copy_lppn(self):
        try:QApplication.clipboard().setText(self._current_lppn());self.statusBar().showMessage('LPPN copied to clipboard',4000)
        except ValueError as exc:QMessageBox.warning(self,'Copy LPPN',str(exc))

    def _export_lppn(self):
        try:
            text=self._current_lppn();self._ensure_default_dir()
            path,_=QFileDialog.getSaveFileName(self,'Export LPPN',DEFAULT_KYPHO_DIR,'LPPN Position (*.lppn)')
            if path:
                from engine.session import atomic_write
                atomic_write(path if path.lower().endswith('.lppn') else path+'.lppn',text+'\n')
        except (OSError,ValueError) as exc:QMessageBox.critical(self,'Export LPPN',str(exc))

    def _export_position_image(self):
        self._ensure_default_dir()
        path, selected = QFileDialog.getSaveFileName(self, 'Export Position Image', DEFAULT_KYPHO_DIR,
                                                    'PNG Image (*.png);;JPEG Image (*.jpg *.jpeg)')
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix not in ('.png', '.jpg', '.jpeg'):
            path += '.jpg' if selected.startswith('JPEG') else '.png'
            suffix = Path(path).suffix.lower()
        image_format = 'JPEG' if suffix in ('.jpg', '.jpeg') else 'PNG'
        if not self.board.grab().save(path, image_format):
            QMessageBox.critical(self, 'Export Position Image', 'Could not save image. Choose a writable folder.')
        else:
            self.statusBar().showMessage('Position image saved: ' + path, 5000)
