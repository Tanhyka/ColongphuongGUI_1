"""Native panel ownership. Board V2 cluster remains a single dock child."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget,QMainWindow,QWidget,QVBoxLayout,QLabel

class DockActions:
    # STEP 7 integration point only: no Notation Tree widget or action yet.
    notation_tree_factory = None

    def _new_dock(self,owner,name,title,widget):
        dock=QDockWidget(title,owner);dock.setObjectName(name)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setWidget(widget)
        return dock

    def _setup_docks(self):
        old=self.takeCentralWidget()
        if old:old.deleteLater()
        self.setDockNestingEnabled(True)
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks | QMainWindow.DockOption.AnimatedDocks)
        self.top_left_container.setMinimumSize(590,390)
        self.notation_container.setMinimumWidth(300)
        self.engine_workspace=QMainWindow(self);self.engine_workspace.setObjectName('engine_workspace_host');self.engine_workspace.setDockNestingEnabled(True)
        self.consider_panel=QWidget();layout=QVBoxLayout(self.consider_panel)
        layout.addWidget(QLabel('Consider'));label=QLabel('Workspace reserved for STEP 6. No analysis is running.');label.setWordWrap(True);layout.addWidget(label);layout.addStretch()
        self.thinking_dock=self._new_dock(self.engine_workspace,'thinking_information','Thinking Information',self.thinking_information)
        self.consider_dock=self._new_dock(self.engine_workspace,'consider','Consider',self.consider_panel)
        self.engine_workspace.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,self.thinking_dock)
        self.engine_workspace.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,self.consider_dock)
        self.engine_workspace.tabifyDockWidget(self.thinking_dock,self.consider_dock);self.thinking_dock.raise_()
        self.board_dock=self._new_dock(self,'board_cluster','Board',self.top_left_container)
        self.notation_dock=self._new_dock(self,'notation','Notation Panel',self.notation_container)
        self.evaluation_dock=self._new_dock(self,'evaluation','Evaluation Graph',self.graph_view)
        self.engine_dock=self._new_dock(self,'engine_workspace','Engine Workspace',self.engine_workspace)
        self.workspace_docks=[self.board_dock,self.notation_dock,self.evaluation_dock,self.engine_dock]
        self.engine_docks=[self.thinking_dock,self.consider_dock]
        self._default_docks()

    def _default_docks(self):
        for dock in self.workspace_docks:
            dock.setFloating(False);self.removeDockWidget(dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.board_dock)
        self.splitDockWidget(self.board_dock,self.notation_dock,Qt.Orientation.Horizontal)
        self.splitDockWidget(self.board_dock,self.evaluation_dock,Qt.Orientation.Vertical)
        self.splitDockWidget(self.evaluation_dock,self.engine_dock,Qt.Orientation.Horizontal)
        for dock in self.engine_docks:
            dock.setFloating(False);self.engine_workspace.removeDockWidget(dock)
            self.engine_workspace.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,dock);dock.show()
        self.engine_workspace.tabifyDockWidget(self.thinking_dock,self.consider_dock);self.thinking_dock.raise_()
        for dock in self.workspace_docks:dock.show()
        self.resizeDocks([self.board_dock,self.notation_dock],[900,300],Qt.Orientation.Horizontal)
        self.resizeDocks([self.board_dock,self.evaluation_dock],[620,180],Qt.Orientation.Vertical)
        self.resizeDocks([self.evaluation_dock,self.engine_dock],[600,600],Qt.Orientation.Horizontal)
        self._schedule_cluster_update()
