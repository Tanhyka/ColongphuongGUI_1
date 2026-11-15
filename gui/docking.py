"""Native panel ownership with full dock nesting, splitting, floating, and tabifying."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QMainWindow, QWidget, QVBoxLayout, QLabel


class DockActions:
    notation_tree_factory = None

    def _new_dock(self, owner, name, title, widget):
        dock = QDockWidget(title, owner)
        dock.setObjectName(name)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(widget)
        dock.topLevelChanged.connect(lambda floating, d=dock: self._on_dock_top_level_changed(d, floating))
        return dock

    def _on_dock_top_level_changed(self, dock: QDockWidget, floating: bool):
        dock.setMinimumSize(180, 70)
        dock.setMaximumSize(16777215, 16777215)
        if floating:
            if dock.width() < 260 or dock.height() < 90:
                dock.resize(max(dock.width(), 420), max(dock.height(), 180))
        self._schedule_cluster_update()

    def _setup_docks(self):
        old = self.takeCentralWidget()
        if old:
            old.deleteLater()

        # Enable free docking: nesting, tabifying, animated docks (omit GroupedDragging
        # so any single dock or tab can detach cleanly into its own floating window).
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
        )

        self.notation_container.setMinimumWidth(200)

        # Consider panel
        self.consider_panel = QWidget()
        c_layout = QVBoxLayout(self.consider_panel)
        c_layout.addWidget(QLabel("<b>Phân tích & Tùy chọn (Consider)</b>"))
        label = QLabel("Khung công cụ phân tích nâng cao và xem trước biến thế.")
        label.setWordWrap(True)
        c_layout.addWidget(label)
        c_layout.addStretch()

        # All docks as top-level docks directly on MainWindow
        self.winrate_dock = self._new_dock(self, "win_probability", "Tỷ lệ thắng (Win Probability)", self.win_percentage)
        self.board_dock = self._new_dock(self, "board_cluster", "Bàn cờ (Board)", self.board_row_widget)
        self.notation_dock = self._new_dock(self, "notation", "Kỳ phổ (Notation)", self.notation_container)
        self.evaluation_dock = self._new_dock(self, "evaluation", "Đồ thị đánh giá (Evaluation)", self.graph_view)
        self.thinking_dock = self._new_dock(self, "thinking_information", "Phân tích Engine (Analysis)", self.thinking_information)
        self.candidates_dock = self._new_dock(self, "engine_candidates", "Nước đi đề xuất (Engine Top 5)", self.candidates_widget)
        self.possible_moves_dock = self._new_dock(self, "possible_moves", "Nước đi hợp lệ (Possible moves)", self.possible_moves_widget)
        self.consider_dock = self._new_dock(self, "consider", "Consider", self.consider_panel)

        # Aliases for compatibility
        self.engine_dock = self.thinking_dock
        self.workspace_docks = [
            self.winrate_dock,
            self.board_dock,
            self.notation_dock,
            self.evaluation_dock,
            self.thinking_dock,
            self.candidates_dock,
            self.possible_moves_dock,
            self.consider_dock,
        ]
        self.all_docks = self.workspace_docks
        self.engine_docks = [self.thinking_dock, self.candidates_dock, self.consider_dock]

        self._default_docks()

    def _default_docks(self):
        """Standard 2-column balanced layout with independent Win Probability & Board docks."""
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.BottomDockWidgetArea)

        for dock in self.all_docks:
            dock.setFloating(False)
            self.removeDockWidget(dock)

        # Left area: Win Probability above Board
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.winrate_dock)

        # Notation beside Left area
        self.splitDockWidget(self.winrate_dock, self.notation_dock, Qt.Orientation.Horizontal)

        # Board below Win Probability
        self.splitDockWidget(self.winrate_dock, self.board_dock, Qt.Orientation.Vertical)

        # Evaluation below Board
        self.splitDockWidget(self.board_dock, self.evaluation_dock, Qt.Orientation.Vertical)

        # Engine Thinking beside Evaluation
        self.splitDockWidget(self.evaluation_dock, self.thinking_dock, Qt.Orientation.Horizontal)

        # Consider, Engine Candidates, Possible Moves tabified with Thinking
        self.tabifyDockWidget(self.thinking_dock, self.candidates_dock)
        self.tabifyDockWidget(self.thinking_dock, self.possible_moves_dock)
        self.tabifyDockWidget(self.thinking_dock, self.consider_dock)
        self.thinking_dock.raise_()

        for dock in (self.winrate_dock, self.board_dock, self.notation_dock, self.evaluation_dock, self.thinking_dock, self.consider_dock):
            dock.show()
        self.candidates_dock.hide()
        self.possible_moves_dock.hide()

        self.resizeDocks([self.winrate_dock, self.notation_dock], [850, 320], Qt.Orientation.Horizontal)
        self.resizeDocks([self.winrate_dock, self.board_dock, self.evaluation_dock], [58, 520, 220], Qt.Orientation.Vertical)
        self.resizeDocks([self.evaluation_dock, self.thinking_dock], [540, 630], Qt.Orientation.Horizontal)
        self._schedule_cluster_update()
