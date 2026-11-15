"""Native file/clipboard/image dialogs backed by the bundled engine codecs."""
from pathlib import Path
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QFileDialog,QMessageBox,QApplication
from engine.game import Game
from engine.lppn import from_lppn,to_lppn
from engine.records import load_record,write_record,history_signature,IllegalRecordMoveError
from gui.constants import BG, get_default_kypho_dir

class FileActions:
    def _install_position_game(self,game,*,editable=True):
        self._leave_review()
        self._tree_undo.clear()
        self._set_force_variation(self.game.current_node,False)
        self._stop_match_runtime(clear_cards=True)
        self._position_editable = bool(editable)
        self.game=game;self.board.game=game;self.is_game_active=False
        self.board.allow_analysis_after_result = True
        self.board._clear_annotations();self.board.reset_transient_state();self.board.set_moves_enabled(bool(editable) and not self.game.is_board_terminal())
        self.notation_view.rebuild_tree(game.root,game.current_node,game.board,game_result=game.result,current_player=game.current)
        self._update_history_and_graph();self._update_menu_states();self._sync_all()

    def _open_record(self, kind=None):
        default_dir = self._ensure_default_dir()
        if kind in ('txt', 'lpgf', 'lppn'):
            filters = {
                'txt': 'Kỳ phổ TXT (*.txt)',
                'lpgf': 'Kỳ phổ LPGF (*.lpgf)',
                'lppn': 'Thế cờ LPPN (*.lppn *.txt)',
            }
            filter_str = filters[kind] + ';;All Files (*)'
        else:
            filter_str = 'Tất cả định dạng hỗ trợ (*.txt *.lpgf *.lppn);;Kỳ phổ LPGF (*.lpgf);;Kỳ phổ TXT (*.txt);;Thế cờ LPPN (*.lppn);;Tất cả file (*)'

        path, _ = QFileDialog.getOpenFileName(
            self,
            'Nhập kỳ phổ CLP (*.txt, *.lpgf, *.lppn)',
            default_dir,
            filter_str
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            for encoding in ('utf-8-sig', 'cp1258'):
                try:
                    content = data.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError('Cannot decode record as UTF-8 or Windows Vietnamese text.')

            if path.lower().endswith('.lppn') or content.strip().startswith('lppn1'):
                self._import_lppn_text(content)
                self.statusBar().showMessage('Nạp thế cờ LPPN thành công: ' + Path(path).name, 6000)
                return

            try:
                game, meta = load_record(content, path)  # failure leaves live board untouched
            except IllegalRecordMoveError as exc:
                move_desc = f"nước thứ {exc.move_no}: {exc.move_text}" if exc.move_text else f"nước thứ {exc.move_no}"
                applied_desc = f"{exc.applied_moves} nước" if exc.applied_moves > 0 else "0 nước (bàn cờ ban đầu)"

                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle("Phát hiện nước đi không hợp lệ")
                box.setText(
                    f"Kỳ phổ này có illegal move ({move_desc}).\n\n"
                    f"Bạn có muốn loại nước illegal move đó không?\n\n"
                    f"• Nếu chọn Có: Hệ thống sẽ nạp hết tới đoạn trước illegal move ({applied_desc}).\n"
                    f"• Nếu chọn Không: Hủy nạp kỳ phổ, giữ nguyên trạng thái bàn cờ hiện tại."
                )
                btn_yes = box.addButton("Có", QMessageBox.ButtonRole.YesRole)
                btn_no = box.addButton("Không", QMessageBox.ButtonRole.NoRole)
                box.setDefaultButton(btn_yes)
                box.exec()

                if box.clickedButton() != btn_yes:
                    self.statusBar().showMessage("Đã hủy nạp kỳ phổ do có nước đi không hợp lệ.", 5000)
                    return

                game = exc.game
                meta = exc.metadata

            self.record_metadata = meta
            self.current_file_path = path
            self._document_dirty = False
            self.card_cam.set_player_name(meta.get('player_cam') or 'Cam')
            self.card_xanh.set_player_name(meta.get('player_xanh') or 'Xanh')
            self._install_position_game(game, editable=True)
            moves_count = len(list(game.nodes())) - 1
            room_info = f" · Phòng: {meta['room_name']}" if meta.get('room_name') else ""
            winner_info = f" · Thắng: {meta['winner']}" if meta.get('winner') else ""
            fmt_name = meta.get('original_format', 'LPGF').upper()
            if 'truncated_illegal_move' in meta or getattr(game, '_truncated_illegal', False):
                self.setWindowTitle(f"ColongphuongGUI - {Path(path).name} (đã cắt đến nước {moves_count})")
                self.statusBar().showMessage(
                    f"Nạp {fmt_name} thành công tới nước {moves_count} (đã loại bỏ nước không hợp lệ){room_info}",
                    7000,
                )
            else:
                self.setWindowTitle('ColongphuongGUI - ' + Path(path).name)
                self.statusBar().showMessage(
                    f"Nạp {fmt_name} thành công: {moves_count} nước{room_info}{winner_info}",
                    6000,
                )
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            QMessageBox.critical(self, 'Open Record', f'Could not open {Path(path).name}:\n{exc}')

    def _write_record_file(self, path, format_type=None, *, adopt=True):
        try:
            text = write_record(
                path,
                self.game,
                self.record_metadata,
                format_type=format_type,
                player_cam=self.card_cam.player_name or 'Cam',
                player_xanh=self.card_xanh.player_name or 'Xanh'
            )
            if adopt:
                self.current_file_path = path
                self._document_dirty = False
                self.record_metadata.update(
                    original_text=text,
                    original_format='lpgf' if path.lower().endswith('.lpgf') else 'txt',
                    signature=history_signature(self.game)
                )
                self.setWindowTitle('ColongphuongGUI - ' + Path(path).name)
            self._save_session()
            self.statusBar().showMessage('Đã xuất kỳ phổ: ' + path, 6000)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, 'Save Record', str(exc))

    def _export_lpgf_11(self):
        self._export_lpgf_20()

    def _export_lpgf_20(self):
        default_dir = self._ensure_default_dir()
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Xuất kỳ phổ LPGF 2.0',
            default_dir,
            'Kỳ phổ LPGF 2.0 (*.lpgf);;Tất cả file (*)'
        )
        if path:
            if not path.lower().endswith('.lpgf'):
                path += '.lpgf'
            self._write_record_file(path, format_type='lpgf20', adopt=False)

    def _export_txt(self):
        default_dir = self._ensure_default_dir()
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Xuất kỳ phổ TXT',
            default_dir,
            'Kỳ phổ TXT (*.txt);;Tất cả file (*)'
        )
        if path:
            if not path.lower().endswith('.txt'):
                path += '.txt'
            self._write_record_file(path, format_type='txt', adopt=False)

    def _export_record_copy(self):
        orig_text = self.record_metadata.get('original_text')
        if not orig_text:
            QMessageBox.information(self, 'Xuất bản sao gốc', 'Không có bản sao gốc của kỳ phổ đã nhập.')
            return
        default_dir = self._ensure_default_dir()
        orig_name = Path(self.current_file_path).name if self.current_file_path else "ky_pho"
        stem = Path(orig_name).stem
        ext = Path(orig_name).suffix or ".lpgf"
        default_copy = str(Path(default_dir) / f"{stem}_copy{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Xuất bản sao gốc',
            default_copy,
            f"Kỳ phổ (*{ext});;Tất cả file (*)"
        )
        if path:
            Path(path).write_bytes(orig_text.encode('utf-8'))
            self.statusBar().showMessage('Đã xuất bản sao gốc: ' + path, 6000)

    def _export_lpgf(self):
        self._export_lpgf_20()

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
        default_dir = self._ensure_default_dir();path,_=QFileDialog.getOpenFileName(self,'Import LPPN',default_dir,'LPPN Position (*.lppn *.txt);;All Files (*)')
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
            text=self._current_lppn();default_dir = self._ensure_default_dir()
            path,_=QFileDialog.getSaveFileName(self,'Export LPPN',default_dir,'LPPN Position (*.lppn)')
            if path:
                from engine.session import atomic_write
                atomic_write(path if path.lower().endswith('.lppn') else path+'.lppn',text+'\n')
        except (OSError,ValueError) as exc:QMessageBox.critical(self,'Export LPPN',str(exc))

    def _capture_board_with_komadai(self) -> QPixmap:
        """Capture the board cluster together with both Komadai stands."""
        row_widget = getattr(self, "board_row_widget", None)
        if row_widget is None or row_widget.width() <= 0 or row_widget.height() <= 0:
            return self.board.grab()

        content_rect = self.board.geometry()
        for panel_name in ("left_panel_widget", "right_panel_widget"):
            panel = getattr(self, panel_name, None)
            if panel is not None and not panel.isHidden() and panel.width() > 0 and panel.height() > 0:
                content_rect = content_rect.united(panel.geometry())
        content_rect = content_rect.intersected(row_widget.rect())
        if content_rect.isEmpty():
            return self.board.grab()

        captured = row_widget.grab(content_rect)
        pad = 12
        out = QPixmap(captured.width() + 2 * pad, captured.height() + 2 * pad)
        out.fill(QColor(BG))
        painter = QPainter(out)
        painter.drawPixmap(QPoint(pad, pad), captured)
        painter.end()
        return out

    def _export_position_image(self):
        default_dir = self._ensure_default_dir()
        path, selected = QFileDialog.getSaveFileName(self, 'Export Position Image', default_dir,
                                                    'PNG Image (*.png);;JPEG Image (*.jpg *.jpeg)')
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix not in ('.png', '.jpg', '.jpeg'):
            path += '.jpg' if selected.startswith('JPEG') else '.png'
            suffix = Path(path).suffix.lower()
        image_format = 'JPEG' if suffix in ('.jpg', '.jpeg') else 'PNG'
        pixmap = self._capture_board_with_komadai()
        if not pixmap.save(path, image_format):
            QMessageBox.critical(self, 'Export Position Image', 'Could not save image. Choose a writable folder.')
        else:
            self.statusBar().showMessage('Position image saved: ' + path, 5000)
