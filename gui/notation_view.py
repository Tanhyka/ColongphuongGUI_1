"""Notation tree view and game navigation component."""

from typing import Optional, Dict
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from engine.game import MoveNode
from engine.board import Board
from engine.pieces import Player
from gui.constants import PANEL, BORDER, TEXT
from gui.helpers import Panel

NAV_BTN_STYLE = f"""
    QPushButton {{
        background-color: #ffffff;
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 4px;
        font-weight: bold;
        font-size: 13px;
        padding: 4px 0px;
        min-height: 24px;
    }}
    QPushButton:hover {{
        background-color: #eef6fc;
        color: #0f6fa8;
        border-color: #badcf5;
    }}
    QPushButton:pressed {{
        background-color: #dceefc;
    }}
    QPushButton:disabled {{
        background-color: #f8fafc;
        color: #cbd5e1;
        border-color: #e2e8f0;
    }}
"""

TREE_STYLE = f"""
    QTreeWidget {{
        background-color: #ffffff;
        alternate-background-color: #f8fafc;
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 4px;
        outline: none;
        font-size: 12px;
    }}
    QTreeWidget::item {{
        padding: 4px 6px;
        color: {TEXT};
    }}
    QTreeWidget::item:selected {{
        background-color: #e2f0fa;
        color: #0f6fa8;
        font-weight: bold;
    }}
    QHeaderView::section {{
        background-color: #f1f5f9;
        color: #334155;
        padding: 4px 8px;
        font-weight: bold;
        border: none;
        border-bottom: 1px solid {BORDER};
    }}
"""


class NotationView(Panel):
    """Displays move history in an interactive tree view with branching navigation."""

    node_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(340)

        self.root_node: Optional[MoveNode] = None
        self.current_node: Optional[MoveNode] = None
        self.node_to_item: Dict[int, QTreeWidgetItem] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Header (Title + Navigation controls)
        header = QWidget()
        header.setStyleSheet(f"""
            QWidget {{
                background: {PANEL};
                border-bottom: 1px solid {BORDER};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(8)

        title = QLabel("Kifu / Notation Tree")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 800; border: none;")
        header_layout.addWidget(title)

        nav_box = QHBoxLayout()
        nav_box.setSpacing(4)
        nav_box.setContentsMargins(0, 0, 0, 0)

        self.btn_first = QPushButton("|<")
        self.btn_prev = QPushButton("<")
        self.btn_next = QPushButton(">")
        self.btn_last = QPushButton(">|")

        for btn, handler in [
            (self.btn_first, self._go_first),
            (self.btn_prev, self._go_prev),
            (self.btn_next, self._go_next),
            (self.btn_last, self._go_last),
        ]:
            btn.setStyleSheet(NAV_BTN_STYLE)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            nav_box.addWidget(btn)

        header_layout.addLayout(nav_box)
        root_layout.addWidget(header)

        # 2. Content (Move list tree)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Move / Variation", "Side"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.setIndentation(18)
        self.tree.setUniformRowHeights(True)

        header_view = self.tree.header()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.headerItem().setTextAlignment(
            1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.tree.setStyleSheet(TREE_STYLE)

        content_layout.addWidget(self.tree)
        root_layout.addWidget(content, 1)

        self._update_nav_states()

    def _update_nav_states(self):
        """Synchronizes navigation button states based on current node position."""
        has_root = self.root_node is not None
        is_at_root = not self.current_node or self.current_node == self.root_node
        has_children = bool(self.current_node and self.current_node.children)

        can_go_back = has_root and not is_at_root
        self.btn_first.setEnabled(can_go_back)
        self.btn_prev.setEnabled(can_go_back)
        self.btn_next.setEnabled(has_children)
        self.btn_last.setEnabled(has_children)

    def set_current_node(self, node: MoveNode):
        """Highlights the active node in the tree and updates navigation."""
        self.current_node = node
        self._update_nav_states()

        item = self.node_to_item.get(id(node))
        self.tree.blockSignals(True)
        if item:
            ancestor=item.parent()
            while ancestor is not None:
                ancestor.setExpanded(True);ancestor=ancestor.parent()
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        else:
            self.tree.clearSelection()
        self.tree.blockSignals(False)

    def _select_and_emit(self, node: Optional[MoveNode]):
        if node:
            self.set_current_node(node)
            self.node_selected.emit(node)

    def _go_first(self):
        self._select_and_emit(self.root_node)

    def _go_prev(self):
        if self.current_node and self.current_node.parent:
            self._select_and_emit(self.current_node.parent)

    def _go_next(self):
        if self.current_node and self.current_node.children:
            self._select_and_emit(self.current_node.children[0])

    def _go_last(self):
        if self.current_node:
            curr = self.current_node
            while curr.children:
                curr = curr.children[0]
            self._select_and_emit(curr)

    def _on_selection_changed(self):
        selected_items = self.tree.selectedItems()
        if selected_items:
            node = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if node:
                self.current_node = node
                self._update_nav_states()
                self.node_selected.emit(node)

    def rebuild_tree(
        self,
        root_node: MoveNode,
        current_node: MoveNode,
        board: Optional[Board] = None,
        game_result: Optional[str] = None,
        current_player: Optional[Player] = None,
    ):
        """Reconcile existing items by object identity; never clear on navigation.

        Main continuations share a row level, alternatives attach to their
        parent position. Iterative traversal also supports deeply nested games.
        """
        changed_root = self.root_node is not root_node
        self.root_node = root_node
        self.tree.blockSignals(True)
        try:
            if changed_root:
                self.tree.clear()
                self.node_to_item.clear()
            queue = [(root_node, 0)]
            ordered = []
            containers = {}
            alive = set()
            while queue:
                node, depth = queue.pop()
                ordered.append((node,depth))
                key = id(node);alive.add(key)
                item = self.node_to_item.get(key)
                if item is None:
                    item = QTreeWidgetItem()
                    self.node_to_item[key] = item
                if node.parent is None:
                    visual_parent = self.tree.invisibleRootItem()
                    containers[key] = item
                    label = 'Start position'
                    side = node._snapshot_current
                else:
                    parent_item = self.node_to_item[id(node.parent)]
                    first = node.parent.children[0] is node
                    visual_parent = containers[id(node.parent)] if first else parent_item
                    containers[key] = containers[id(node.parent)] if first else item
                    label = f'{depth}. {node.notation_text or "Move"}'
                    if not first:label = 'Variation: ' + label
                    side = node.parent._snapshot_current
                if item.parent() is not visual_parent:
                    old_parent = item.parent() or self.tree.invisibleRootItem()
                    index = old_parent.indexOfChild(item)
                    if index >= 0:old_parent.takeChild(index)
                    visual_parent.addChild(item)
                item.setText(0, label + (' ' + ' '.join(node.glyphs) if node.glyphs else ''))
                item.setText(1, side.name if side else '')
                item.setToolTip(0, (node.comment + ('\n' + node.result if node.result else '')).strip())
                item.setData(0, Qt.ItemDataRole.UserRole, node)
                queue.extend((c,depth+1) for c in reversed(node.children))
            # Hold every removed wrapper until its children have been detached.
            # Releasing a parent first deletes its C++ children behind Python's
            # surviving child wrappers.
            removed = [self.node_to_item.pop(key) for key in list(self.node_to_item) if key not in alive]
            for item in removed:
                parent=item.parent() or self.tree.invisibleRootItem()
                index=parent.indexOfChild(item)
                if index>=0:parent.takeChild(index)
            # Reconcile order after promotion without recreating items.
            desired={}
            for node,depth in ordered:
                item=self.node_to_item[id(node)]
                parent=item.parent() or self.tree.invisibleRootItem()
                desired.setdefault(id(parent),(parent,[]))[1].append(item)
            for parent,items in desired.values():
                for index,item in enumerate(items):
                    old=parent.indexOfChild(item)
                    if old!=index:
                        parent.takeChild(old);parent.insertChild(index,item)
            if changed_root:
                self.node_to_item[id(root_node)].setExpanded(True)
        finally:
            self.tree.blockSignals(False)
        self.set_current_node(current_node)
