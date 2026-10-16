"""Position-editor inventory helpers shared by GUI and future tooling."""

from collections import Counter
from typing import Dict, Tuple

from .board import Board, SIZE
from .pieces import PieceType, Player


# Total physical inventory in one complete Co Long Phuong set.
STANDARD_TOTALS: Dict[PieceType, int] = {
    PieceType.VUONG: 2,
    PieceType.LONG: 2,
    PieceType.PHUONG: 2,
    PieceType.TUONG: 4,
    PieceType.SI: 4,
    PieceType.KI: 4,
    PieceType.XA: 4,
    PieceType.BINH: 18,
}

# Vương is tracked separately by side in the editor UI.
STANDARD_KINGS_PER_SIDE = 1


def position_counts(board: Board) -> Tuple[Counter, Dict[Player, int]]:
    """Count every piece on the board and in both hands/reserves.

    Hand pieces in the engine are represented by PieceType only. Vương is never
    normally a hand piece, so side-specific king counts come from board pieces.
    """
    totals = Counter()
    king_by_side = {Player.CAM: 0, Player.XANH: 0}

    for r in range(SIZE):
        for c in range(SIZE):
            for piece in board.sq(r, c).stack:
                totals[piece.ptype] += 1
                if piece.ptype is PieceType.VUONG:
                    king_by_side[piece.owner] += 1

    for player in Player:
        for ptype in board.reserve[player]:
            totals[ptype] += 1
        for ptype in board.prisoners[player]:
            totals[ptype] += 1

    return totals, king_by_side


def position_has_overflow(board: Board) -> bool:
    """Whether any physical inventory limit is exceeded."""
    totals, kings = position_counts(board)
    if kings[Player.CAM] > STANDARD_KINGS_PER_SIDE:
        return True
    if kings[Player.XANH] > STANDARD_KINGS_PER_SIDE:
        return True
    return any(totals[ptype] > maximum for ptype, maximum in STANDARD_TOTALS.items())


def clear_position(board: Board) -> None:
    """Remove all board pieces and all pieces from both hands/reserves."""
    for r in range(SIZE):
        for c in range(SIZE):
            board.sq(r, c).stack.clear()
    for player in Player:
        board.reserve[player].clear()
        board.prisoners[player].clear()


def fill_hand(board: Board, player: Player) -> bool:
    """Put every missing non-king piece into ``player``'s hand.

    Fill is intentionally all-or-nothing with respect to invalid inventory: if
    *any* type is already above the physical maximum, nothing is changed and
    False is returned. This matches the editor UI rule that both Fill Hand
    buttons are disabled whenever the position is over-count.

    Vương is excluded because it cannot be held/dropped from a komadai.
    """
    if position_has_overflow(board):
        return False

    totals, _ = position_counts(board)
    for ptype, maximum in STANDARD_TOTALS.items():
        if ptype is PieceType.VUONG:
            continue
        missing = max(0, maximum - totals[ptype])
        if missing:
            board.prisoners[player].extend([ptype] * missing)
    return True
