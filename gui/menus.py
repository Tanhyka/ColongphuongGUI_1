"""Menu construction; existing action callbacks remain on MainWindow."""
from PyQt6.QtGui import QAction,QKeySequence

class MenuActions:
    def _setup_menu_bar(self):
        mb = self.menuBar()
        mb.setStyleSheet(self.menu_bar_style)

        # 1. FILE (F)
        file_menu = mb.addMenu("File(F)")
        self.act_new = QAction("New(N)", self)
        self.act_new.triggered.connect(self._on_action_new)
        file_menu.addAction(self.act_new)

        open_menu = file_menu.addMenu("Open")
        self.act_open = open_menu.addAction("TXT...", lambda: self._open_record('txt'))
        self.act_open.setShortcut(QKeySequence("Ctrl+O"))
        open_menu.addAction("LPGF...", lambda: self._open_record('lpgf'))
        open_menu.addAction("LPPN...", self._open_lppn)
        open_menu.addAction("Paste LPPN", self._paste_lppn)
        self.act_save = file_menu.addAction("Save", self._on_action_save)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save_as = file_menu.addAction("Save As...", self._on_action_save_as)
        self.act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        export_menu = file_menu.addMenu("Export")
        export_menu.addAction("Export LPGF...", self._export_lpgf)
        export_menu.addAction("Export LPPN...", self._export_lppn)
        export_menu.addAction("Copy LPPN", self._copy_lppn)
        export_menu.addAction("Export Position Image...", self._export_position_image)
        file_menu.addAction("Recover Previous Session...", self._recover_previous_session)
        file_menu.addSeparator()
        act_exit = file_menu.addAction("Exit", self.close)
        act_exit.setShortcut(QKeySequence("Alt+F4"))

        # 2. EDIT (E)
        edit_menu = mb.addMenu("Edit(E)")
        undo_tree = edit_menu.addAction('Undo tree edit',self._undo_tree_edit)
        undo_tree.setShortcut(QKeySequence('Ctrl+Alt+Z'))
        edit_menu.addAction('Enter moves from this position',lambda:self.board.set_moves_enabled(not self.is_game_active and not self._review_active and not self.game.is_over()))
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

        # (b) Bật / Tắt Biểu đồ đánh giá thế trận (Graph View)
        self.act_view_graph = self.evaluation_dock.toggleViewAction()
        self.act_view_graph.setText("Display Evaluation (Evaluation Graph)")
        view_menu.addAction(self.act_view_graph)

        # (c) Bật / Tắt Nhãn số định vị tọa độ (a-i, 1-9)
        self.act_view_coords = QAction("Coordinates(C)", self)
        self.act_view_coords.setCheckable(True)
        self.act_view_coords.setChecked(True)
        self.act_view_coords.toggled.connect(self.board.set_show_coordinates)
        view_menu.addAction(self.act_view_coords)

        # (d) Bật / Tắt Bảng kỳ phổ bên phải
        self.act_view_notation = self.notation_dock.toggleViewAction()
        view_menu.addAction(self.act_view_notation)

        # (e) Bật / Tắt thanh phần trăm thắng ở phía trên
        self.act_view_winrate = QAction("Winning percentage(W)", self)
        self.act_view_winrate.setCheckable(True)
        self.act_view_winrate.setChecked(True)
        self.act_view_winrate.toggled.connect(self.win_percentage.setVisible)
        view_menu.addAction(self.act_view_winrate)

        # (f) Bật / Tắt bảng thông tin suy nghĩ của engine
        self.act_view_thinking = self.thinking_dock.toggleViewAction()
        view_menu.addAction(self.act_view_thinking)

        windows = view_menu.addMenu("Windows")
        for dock in self.workspace_docks + self.engine_docks:
            action = dock.toggleViewAction()
            windows.addAction(action)
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

