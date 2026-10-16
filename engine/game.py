

from collections import Counter
import uuid
from typing import Optional, List
from .board import Board, SIZE
from .pieces import Player
from . import rules


def _position_hash(board: Board, player_to_move: Player) -> str:
    """Generates a unique state key for repetition detection."""
    parts = [player_to_move.name]
    for r in range(SIZE):
        for c in range(SIZE):
            st = board.sq(r, c).stack
            if st:
                cell = "".join(f"{p.owner.name[0]}{p.ptype.name}{p.facing}" for p in st)
                parts.append(f"{r},{c}:{cell}")
    # Hand state is part of a position. Sort values so equivalent multisets
    # hash identically regardless of capture/removal order.
    for pl in Player:
        reserve = ",".join(sorted(pt.name for pt in board.reserve[pl]))
        prisoners = ",".join(sorted(pt.name for pt in board.prisoners[pl]))
        parts.append(f"R:{pl.name}={reserve}")
        parts.append(f"P:{pl.name}={prisoners}")
    return "|".join(parts)


def _same_move(a: Optional[rules.Move], b: Optional[rules.Move]) -> bool:
    """Checks equality between two move definitions."""
    if a is None or b is None:
        return a == b
    return (
        a.kind == b.kind
        and a.src == b.src
        and a.dst == b.dst
        and a.ptype == b.ptype
        and a.facing == b.facing
        and a.rotate_after == b.rotate_after
    )


class MoveNode:
    """Node in the game move tree supporting branching variations.

    Each node can also cache the full game state *after* that node.  A board is
    tiny (9x9), so this trades a small amount of RAM for instant record
    navigation instead of replaying every move from the root on each click.
    """

    def __init__(
        self,
        move: Optional[rules.Move] = None,
        parent: Optional['MoveNode'] = None,
        notation_text: str = "",
    ):
        self.move = move
        self.node_id = uuid.uuid4().hex
        self.glyphs = []
        self.metadata = {}
        self.parent = parent
        self.children: List['MoveNode'] = []
        self.comment = ""
        self.notation_text = notation_text
        self.result: Optional[str] = None

        # Step 3.5.1 replay cache.  Kept private-ish so old callers that only
        # know MoveNode(move/parent/children) remain fully compatible.
        self._snapshot_board: Optional[Board] = None
        self._snapshot_current: Optional[Player] = None
        self._snapshot_result: Optional[str] = None
        self._snapshot_pos_counts: Optional[Counter] = None

    def add_child(self, move: rules.Move, notation_text: str = "") -> 'MoveNode':
        """Appends or returns an existing move child node."""
        for child in self.children:
            if _same_move(child.move, move):
                if notation_text and not child.notation_text:
                    child.notation_text = notation_text
                return child
        new_node = MoveNode(move, parent=self, notation_text=notation_text)
        self.children.append(new_node)
        return new_node


def _standard_initial_board() -> Board:
    board = Board()
    board.setup_initial()
    return board


class Game:
    """Coordinates match state, history navigation, move validation, and game loop."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Resets the game and its root/base position to the standard opening."""
        self.set_base_position(_standard_initial_board(), Player.CAM)

    def _store_snapshot(self, node: Optional[MoveNode] = None) -> None:
        """Cache the current state on ``node`` for O(1) history navigation."""
        node = node or self.current_node
        node._snapshot_board = self.board.clone()
        node._snapshot_current = self.current
        node._snapshot_result = self.result
        node._snapshot_pos_counts = Counter(self.pos_counts)

    def refresh_current_snapshot(self) -> None:
        """Refresh the cache after a non-move result change (mate marker/resign)."""
        self.current_node.result = self.result
        self._store_snapshot(self.current_node)

    def _restore_snapshot(self, node: MoveNode) -> bool:
        board = getattr(node, "_snapshot_board", None)
        current = getattr(node, "_snapshot_current", None)
        counts = getattr(node, "_snapshot_pos_counts", None)
        if board is None or current is None or counts is None:
            return False
        self.board = board.clone()
        self.current = current
        self.result = getattr(node, "_snapshot_result", None)
        self.pos_counts = Counter(counts)
        self.current_node = node
        return True

    def set_base_position(self, board: Board, player_to_move: Player = Player.CAM):
        """Install a new root position and clear all move history.

        This is the engine foundation used by Edit Position.  The supplied board
        is cloned so later editor/UI mutations cannot silently alter the saved
        root position.
        """
        if not isinstance(player_to_move, Player):
            raise ValueError("player_to_move must be a Player")

        self.max_plies = None
        self.base_ply = 0
        self.base_board = board.clone()
        self.base_current = player_to_move
        self.board = self.base_board.clone()
        self.current = self.base_current
        self.root = MoveNode()
        self.game_id = uuid.uuid4().hex
        self.metadata = {}
        self.current_node = self.root
        self.pos_counts = Counter()
        self.result: Optional[str] = None
        self.pos_counts[_position_hash(self.board, self.current)] += 1
        self._store_snapshot(self.root)

    def get_base_position(self):
        """Return an independent (board, player_to_move) snapshot of the root."""
        return self.base_board.clone(), self.base_current

    def has_custom_base_position(self) -> bool:
        """Whether the game starts from something other than the standard opening."""
        standard = _standard_initial_board()
        return _position_hash(self.base_board, self.base_current) != _position_hash(standard, Player.CAM)

    def legal_moves(self) -> List[rules.Move]:
        return [] if self.result is not None else rules.legal_moves(self.board, self.current)

    def in_check(self, player: Optional[Player] = None) -> bool:
        return rules.is_in_check(self.board, player or self.current)

    def commit_prevalidated_move(
        self,
        move: rules.Move,
        notation_text: Optional[str] = None,
        *,
        check_terminal: bool = True,
    ) -> bool:
        """Apply a move that the caller has already established is legal.

        Record loading first resolves a move against the current position.  The
        old path then called ``make_move`` and generated *all* legal moves a
        second time.  This helper removes that duplicate work while preserving
        history, repetition tracking and optional terminal detection.
        """
        if self.result is not None:
            return False

        if notation_text is None:
            try:
                notation_text = move.notation(self.board) or ""
            except Exception:
                notation_text = move.notation() or ""

        player_moved = self.current
        rules.apply_move(self.board, player_moved, move)
        self.current_node = self.current_node.add_child(move, notation_text=notation_text or "")

        nxt = rules.other(player_moved)
        key = _position_hash(self.board, nxt)
        self.pos_counts[key] += 1

        # Threefold repetition rule (Thien Nhat Thu) is cheap and must remain
        # active during fast record loading because it depends on the full path.
        if self.pos_counts[key] >= 3:
            self.result = f"{player_moved.name} thua (Thien Nhat Thu - lap lai the co 3 lan)"
            self.current = nxt
            self.current_node.result = self.result
            self._store_snapshot(self.current_node)
            return True

        self.current = nxt
        if check_terminal:
            status = rules.game_status(self.board, self.current)
            if status == 'checkmate':
                self.result = f"{rules.other(self.current).name} thang (Chieu het)"
            elif status == 'stalemate':
                self.result = f"{rules.other(self.current).name} thang (Doi thu bi PAT)"

        if self.result is None and self.max_plies is not None:
            node = self.current_node
            depth = 0
            while node.parent is not None:
                depth += 1
                node = node.parent
            if depth >= self.max_plies:
                self.result = "Draw (maximum plies reached)"
        self.current_node.result = self.result
        self._store_snapshot(self.current_node)
        return True

    def make_move(self, move: rules.Move) -> bool:
        """Executes a move, tracks position history, and checks termination conditions."""
        if self.result is not None or not any(_same_move(move, m) for m in self.legal_moves()):
            return False
        return self.commit_prevalidated_move(move, check_terminal=True)

    def resign(self):
        """Current player forfeits the game."""
        if self.result is None:
            winner = rules.other(self.current)
            self.result = f"{self.current.name} xin thua - {winner.name} thang"
            self.current_node.result = self.result
            self._store_snapshot(self.current_node)

    def forfeit(self, loser: Player, display: Optional[str] = None) -> None:
        """Record a timeout/engine forfeit without depending on external DLL."""
        if self.result is not None:
            return
        if not isinstance(loser, Player):
            raise ValueError("Loser must be CAM or XANH")
        winner = rules.other(loser)
        self.result = display or f"{loser.name} thua - {winner.name} thang"
        self.current_node.result = self.result
        self._store_snapshot(self.current_node)

    def is_over(self) -> bool:
        return self.result is not None

    def go_to_node(self, node: MoveNode):
        """Restore a history node, normally from its cached 9x9 snapshot.

        Before Step 3.5.1 this replayed every move from the root and ran a full
        ``game_status()`` (therefore full legal-move generation) after every
        ply.  On high-branching records that made each Previous/Next click take
        seconds.  New nodes cache their states; the legacy fallback below also
        populates caches as it reconstructs older in-memory trees.
        """
        if self._restore_snapshot(node):
            return

        path: List[MoveNode] = []
        curr = node
        while curr.parent is not None:
            path.append(curr)
            curr = curr.parent
        path.reverse()

        self.board = self.base_board.clone()
        self.current = self.base_current
        self.result = None
        self.pos_counts = Counter()
        self.pos_counts[_position_hash(self.board, self.current)] += 1
        self.current_node = self.root
        self._store_snapshot(self.root)

        for n in path:
            if not n.notation_text and n.move:
                try:
                    n.notation_text = n.move.notation(self.board) or ""
                except Exception:
                    pass

            player_moved = self.current
            rules.apply_move(self.board, player_moved, n.move)
            self.current = rules.other(player_moved)

            key = _position_hash(self.board, self.current)
            self.pos_counts[key] += 1
            if self.pos_counts[key] >= 3:
                self.result = f"{player_moved.name} thua (Thien Nhat Thu - lap lai the co 3 lan)"
            elif n.result is not None:
                self.result = n.result
            else:
                # Do not regenerate every legal move merely to browse history.
                # Imported/live nodes already carry result snapshots.  For a
                # legacy cache-less tree, result=None means this intermediate
                # node is non-terminal for navigation purposes.
                self.result = None

            self.current_node = n
            self._store_snapshot(n)
            if self.result is not None:
                break

        if node.result is not None:
            self.result = node.result
        self.current_node = node
        self._store_snapshot(node)

    def nodes(self):
        """Breadth first order, retaining explicit sibling order."""
        queue = [self.root]
        seen = set()
        for node in queue:
            if id(node) in seen:
                raise ValueError('Cyclic or shared move node')
            seen.add(id(node))
            yield node
            queue.extend(node.children)

    def contains_node(self, node):
        while node.parent is not None:
            if node not in node.parent.children:
                return False
            node = node.parent
        return node is self.root

    def promote(self, node):
        if not self.contains_node(node) or node is self.root:
            raise ValueError('Invalid variation')
        # Promote at every branching point on the chosen path.
        while node.parent is not None:
            siblings = node.parent.children
            siblings.remove(node)
            siblings.insert(0, node)
            node = node.parent

    def delete_branch(self, node):
        if not self.contains_node(node) or node is self.root:
            raise ValueError('Cannot delete root or foreign node')
        selected = self.current_node
        while selected is not None and selected is not node:
            selected = selected.parent
        parent = node.parent
        if selected is node:
            self.go_to_node(parent)
        parent.children.remove(node)
        node.parent = None
