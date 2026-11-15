"""Menu construction; existing action callbacks remain on MainWindow."""
from PyQt6.QtGui import QAction,QKeySequence

class MenuActions:
    def _setup_menu_bar(self):
        mb = self.menuBar()
        mb.setStyleSheet(self.menu_bar_style)

        # 1. FILE (F)
        file_menu = mb.addMenu("&Tệp (File)")

        self.act_open = file_menu.addAction("Nhập Kỳ phổ (TXT / LPGF / LPPN)...", self._open_record)
        self.act_open.setObjectName("importAction")
        self.act_open.setShortcut(QKeySequence("Ctrl+O"))

        self.export_as_menu = file_menu.addMenu("Xuất kỳ phổ (Export As)...")
        self.exportAsMenu_ = self.export_as_menu
        act_exp_20 = self.export_as_menu.addAction("Xuất thành LPGF 2.0 (*.lpgf)...", self._export_lpgf_20)
        act_exp_20.setObjectName("exportLpgf20Action")
        act_exp_txt = self.export_as_menu.addAction("Xuất thành TXT (*.txt)...", self._export_txt)
        act_exp_txt.setObjectName("exportTxtAction")

        self.act_export_copy = file_menu.addAction("Xuất bản sao gốc...", self._export_record_copy)
        self.act_export_copy.setObjectName("exportCopyAction")

        self.lppn_menu = file_menu.addMenu("LPPN (Thế cờ / SFEN)")
        self.lppn_menu.addAction("Xuất LPPN (*.lppn)...", self._export_lppn)
        self.lppn_menu.addAction("Sao chép LPPN (Copy)", self._copy_lppn)
        self.lppn_menu.addAction("Dán LPPN (Paste)", self._paste_lppn)

        file_menu.addAction("Xuất hình ảnh bàn cờ (Image)...", self._export_position_image)

        file_menu.addSeparator()

        self.act_new = QAction("Tạo mới ván đấu / Khởi tạo lại", self)
        self.act_new.setObjectName("resetBoardAction")
        self.act_new.setShortcut(QKeySequence("Ctrl+N"))
        self.act_new.triggered.connect(self._on_action_new)
        file_menu.addAction(self.act_new)

        self.act_save = file_menu.addAction("Lưu tạm thời phiên làm việc (Save Session)", self._on_action_save)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save_as = file_menu.addAction("Lưu ván đấu thành file khác (Save As)...", self._on_action_save_as)
        self.act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        file_menu.addAction("Khôi phục phiên làm việc trước...", self._recover_previous_session)

        file_menu.addSeparator()
        act_exit = file_menu.addAction("Thoát (Exit)", self.close)
        act_exit.setShortcut(QKeySequence("Alt+F4"))

        # 2. EDIT (E)
        edit_menu = mb.addMenu("Edit(E)")
        undo_tree = edit_menu.addAction('Undo tree edit',self._undo_tree_edit)
        undo_tree.setShortcut(QKeySequence('Ctrl+Alt+Z'))
        edit_menu.addAction('Enter moves from this position', lambda: (setattr(self, '_position_editable', True), self.board.set_moves_enabled(not self.is_game_active and not self._review_active and not self.game.is_over())))
        edit_menu.addAction('Cancel force variation',lambda:self._set_force_variation(self.game.current_node,False))

        # 3. VIEW (V) - MENU QUẢN LÝ ẨN / HIỆN CÁC KHUNG
        view_menu = mb.addMenu("View(V)")
        profiles = view_menu.addMenu("Profile")
        for side in ("cam", "xanh"):
            sub_menu = profiles.addMenu(side.capitalize())
            act_pic = QAction("Add picture", self)
            act_pic.triggered.connect(lambda _, s=side: self._edit_picture(s))
            sub_menu.addAction(act_pic)

            act_name = QAction("Rename", self)
            act_name.triggered.connect(lambda _, s=side: self._edit_name(s))
            sub_menu.addAction(act_name)

            act_rank = QAction("Add ranking", self)
            act_rank.triggered.connect(lambda _, s=side: self._edit_ranking(s))
            sub_menu.addAction(act_rank)


        
        act_turn_board = QAction("Turn board(T)", self)
        act_turn_board.setShortcut(QKeySequence("Ctrl+T"))
        act_turn_board.triggered.connect(self._on_turn_board)
        view_menu.addAction(act_turn_board)

        view_menu.addSeparator()

        # (a) Bật / Tắt Action Toolbar
        self.act_view_toolbar = QAction("Action Toolbar", self)
        self.act_view_toolbar.setCheckable(True)
        self.act_view_toolbar.setChecked(True)
        self.act_view_toolbar.toggled.connect(self.board.set_toolbar_visible)
        view_menu.addAction(self.act_view_toolbar)

        # (b) Bật / Tắt Nhãn số định vị tọa độ (a-i, 1-9)
        self.act_view_coords = QAction("Coordinates(C)", self)
        self.act_view_coords.setCheckable(True)
        self.act_view_coords.setChecked(True)
        self.act_view_coords.toggled.connect(self.board.set_show_coordinates)
        view_menu.addAction(self.act_view_coords)

        # (c) Bật / Tắt mũi tên đề xuất Engine trên bàn cờ
        self.act_toggle_arrows = QAction("Mũi tên đề xuất Engine (MultiPV Arrows)", self)
        self.act_toggle_arrows.setCheckable(True)
        self.act_toggle_arrows.setChecked(getattr(self, "show_arrows", True))
        self.act_toggle_arrows.toggled.connect(self._on_toggle_engine_arrows)
        view_menu.addAction(self.act_toggle_arrows)

        view_menu.addSeparator()

        # (d) Gộp toàn bộ các cửa sổ / Dock trực tiếp vào View(V), không trùng lặp
        self.act_view_winrate = self.winrate_dock.toggleViewAction()
        self.act_view_winrate.setText("Winning percentage(W)")
        self.act_view_board = self.board_dock.toggleViewAction()
        self.act_view_notation = self.notation_dock.toggleViewAction()
        self.act_view_graph = self.evaluation_dock.toggleViewAction()
        self.act_view_graph.setText("Display Evaluation (Evaluation Graph)")
        self.act_view_thinking = self.thinking_dock.toggleViewAction()
        self.act_view_candidates = self.candidates_dock.toggleViewAction()
        self.act_view_possible_moves = self.possible_moves_dock.toggleViewAction()
        self.act_view_consider = self.consider_dock.toggleViewAction()

        dock_actions = (
            (self.winrate_dock, self.act_view_winrate),
            (self.board_dock, self.act_view_board),
            (self.notation_dock, self.act_view_notation),
            (self.evaluation_dock, self.act_view_graph),
            (self.thinking_dock, self.act_view_thinking),
            (self.candidates_dock, self.act_view_candidates),
            (self.possible_moves_dock, self.act_view_possible_moves),
            (self.consider_dock, self.act_view_consider),
        )
        for dock, action in dock_actions:
            view_menu.addAction(action)
            action.triggered.connect(lambda checked, d=dock: self._show_workspace_panel(d, checked))

        view_menu.addSeparator()
        view_menu.addAction("Save Layout", lambda: self._save_layout(explicit=True))
        view_menu.addAction("Reset Layout", self._reset_layout)

        # 4. GAME (P)
        game_menu = mb.addMenu("Game(P)")
        self.act_new_game = QAction("New Game(G)", self)
        self.act_new_game.triggered.connect(self._on_start_game)
        game_menu.addAction(self.act_new_game)
        game_menu.addAction("Consider", lambda: self._start_inspection("consider"))
        game_menu.addSeparator()

        self.act_resign = QAction("Resign(R)", self)
        self.act_resign.triggered.connect(self._on_resign)
        game_menu.addAction(self.act_resign)

        self.act_stop = QAction("Stop(S)", self)
        self.act_stop.triggered.connect(self._on_stop_game)
        game_menu.addAction(self.act_stop)
        game_menu.addSeparator()
        self.act_analysis = QAction("Analysis(A)", self)
        self.act_analysis.triggered.connect(self._on_analysis)
        game_menu.addAction(self.act_analysis)

        # 5. EDIT POSITION (B) - opens the editor directly (no submenu).
        self.act_edit_position = QAction("Edit position(B)", self)
        self.act_edit_position.triggered.connect(self._on_edit_position)
        mb.addAction(self.act_edit_position)

        # 6. TOOLS (T)
        tools_menu = mb.addMenu("Tools(T)")
        improvement = tools_menu.addMenu('Engine Improvement')
        improvement.addAction('Training Review',self._enter_review)

        act_engine_settings = QAction("Engine settings(E)", self)
        act_engine_settings.triggered.connect(self._open_engine_settings)
        tools_menu.addAction(act_engine_settings)
        tools_menu.addSeparator()

        act_game_settings = QAction("Game settings(G)", self)
        act_game_settings.triggered.connect(self._open_game_settings)
        tools_menu.addAction(act_game_settings)

        act_consider_settings = QAction("Consider settings(C)", self)
        act_consider_settings.triggered.connect(self._open_consider_settings)
        tools_menu.addAction(act_consider_settings)

        act_hint_settings = QAction("Hint Settings(H)", self)
        act_hint_settings.triggered.connect(self._open_hint_settings)
        tools_menu.addAction(act_hint_settings)

        act_mate_settings = QAction("Mate settings(M)", self)
        act_mate_settings.triggered.connect(self._open_mate_settings)
        tools_menu.addAction(act_mate_settings)
        tools_menu.addSeparator()

        act_options = QAction("Options(O)", self)
        act_options.triggered.connect(self._open_options)
        tools_menu.addAction(act_options)

        free_play = tools_menu.addAction("Free Play Mode (not yet implemented)")
        free_play.setEnabled(False)

        # 7. HELP (H)
        mb.addMenu("Help(H)")

