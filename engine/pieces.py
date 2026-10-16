"""Piece definitions and movement rules for Co Long Phuong."""

from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Tuple


class PieceType(Enum):
    VUONG = auto()   # King (Fixed)
    TUONG = auto()   # Gold General (Rotatable)
    SI = auto()      # Silver General (Rotatable)
    KI = auto()      # Knight-like jumper (Rotatable)
    XA = auto()      # Lance (Rotatable)
    LONG = auto()    # Rook (Fixed)
    PHUONG = auto()  # Bishop (Fixed)
    BINH = auto()    # Pawn (Rotatable)


class Player(Enum):
    CAM = auto()     # Orange / First player (Starts at row 0, facing down = 2)
    XANH = auto()    # Green / Second player (Starts at row 8, facing up = 0)


NON_ROTATABLE = {PieceType.VUONG, PieceType.LONG, PieceType.PHUONG}

PIECE_CODE = {
    PieceType.VUONG: "V",
    PieceType.TUONG: "T",
    PieceType.SI: "S",
    PieceType.KI: "K",
    PieceType.XA: "X",
    PieceType.LONG: "L",
    PieceType.PHUONG: "P",
    PieceType.BINH: "B",
}

# Local movement vectors (Base forward: (-1, 0))
MOVES_LOCAL = {
    PieceType.VUONG: [
        ('step', (-1, -1)), ('step', (-1, 0)), ('step', (-1, 1)),
        ('step', (0, -1)),                     ('step', (0, 1)),
        ('step', (1, -1)),  ('step', (1, 0)),  ('step', (1, 1)),
    ],
    PieceType.TUONG: [
        ('step', (-1, 0)),  ('step', (-1, -1)), ('step', (-1, 1)),
        ('step', (0, -1)),  ('step', (0, 1)),   ('step', (1, 0)),
    ],
    PieceType.SI: [
        ('step', (-1, 0)),  ('step', (-1, -1)), ('step', (-1, 1)),
        ('step', (1, -1)),  ('step', (1, 1)),
    ],
    PieceType.KI: [
        ('jump', (-2, -1)), ('jump', (-2, 1)),
        ('jump', (2, 0)),   ('jump', (2, -2)),  ('jump', (2, 2)),
    ],
    PieceType.XA: [
        ('slide', (-1, 0)),
    ],
    PieceType.LONG: [
        ('slide', (-1, 0)), ('slide', (1, 0)),
        ('slide', (0, -1)), ('slide', (0, 1)),
    ],
    PieceType.PHUONG: [
        ('slide', (-1, -1)), ('slide', (-1, 1)),
        ('slide', (1, -1)),  ('slide', (1, 1)),
    ],
    PieceType.BINH: [
        ('step', (-1, 0)),
    ],
}


def initial_facing(player: Player) -> int:
    """Returns the default facing direction for a player's back-row pieces."""
    return 2 if player is Player.CAM else 0


def rotate_cw(vec: Tuple[int, int], times: int = 1) -> Tuple[int, int]:
    """Rotates a 2D offset vector 90 degrees clockwise `times` times."""
    dr, dc = vec
    t = times % 4
    if t == 1:
        return dc, -dr
    if t == 2:
        return -dr, -dc
    if t == 3:
        return -dc, dr
    return dr, dc


def board_moves_for(piece_type: PieceType, facing: int) -> List[Tuple[str, Tuple[int, int]]]:
    """Translates local piece moves into global board coordinate vectors."""
    effective_facing = 0 if piece_type in NON_ROTATABLE else facing
    return [(kind, rotate_cw(vec, effective_facing)) for kind, vec in MOVES_LOCAL[piece_type]]


@dataclass
class Piece:
    ptype: PieceType
    owner: Player
    facing: int = 0

    def can_rotate(self) -> bool:
        return self.ptype not in NON_ROTATABLE

    def rotate(self, clockwise: bool = True):
        """Rotates the piece in place by 90 degrees."""
        if not self.can_rotate():
            raise ValueError(f"{self.ptype} cannot rotate")
        self.facing = (self.facing + (1 if clockwise else -1)) % 4

    def moves(self) -> List[Tuple[str, Tuple[int, int]]]:
        return board_moves_for(self.ptype, self.facing)

    def code(self) -> str:
        return PIECE_CODE[self.ptype]

    def __repr__(self) -> str:
        side = "C" if self.owner is Player.CAM else "X"
        return f"{side}{self.code()}{self.facing}"