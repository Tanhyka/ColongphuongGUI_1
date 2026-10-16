"""Board and square stack representation for Co Long Phuong."""

from typing import Optional, Tuple
from .pieces import Piece, PieceType, Player, initial_facing

SIZE = 9


class Square:
    """Represents a board square containing an ordered stack of pieces (bottom -> top)."""

    __slots__ = ("stack",)

    def __init__(self):
        self.stack = []

    @property
    def is_empty(self) -> bool:
        return not self.stack

    @property
    def top(self) -> Optional[Piece]:
        return self.stack[-1] if self.stack else None

    @property
    def owner(self) -> Optional[Player]:
        return self.stack[-1].owner if self.stack else None

    def copy(self) -> "Square":
        """Returns an independent copy, including mutable Piece.facing state."""
        sq = Square()
        sq.stack = [Piece(p.ptype, p.owner, p.facing) for p in self.stack]
        return sq


class Board:
    """Game board management, piece stacks, prisoners, and reserves."""

    def __init__(self):
        self.grid = [[Square() for _ in range(SIZE)] for _ in range(SIZE)]
        self.prisoners = {Player.CAM: [], Player.XANH: []}
        self.reserve = {
            Player.CAM: [PieceType.LONG, PieceType.PHUONG],
            Player.XANH: [PieceType.LONG, PieceType.PHUONG],
        }

    @staticmethod
    def in_bounds(r: int, c: int) -> bool:
        return 0 <= r < SIZE and 0 <= c < SIZE

    def sq(self, r: int, c: int) -> Square:
        return self.grid[r][c]

    def setup_initial(self):
        """Initializes the standard starting layout (Long and Phuong are reserved for drop)."""
        back_row_types = [
            PieceType.XA, PieceType.KI, PieceType.SI, PieceType.TUONG,
            PieceType.VUONG, PieceType.TUONG, PieceType.SI, PieceType.KI,
            PieceType.XA,
        ]

        setup_data = [
            (Player.CAM, 0, 2),
            (Player.XANH, 8, 6),
        ]

        for player, back_r, pawn_r in setup_data:
            facing = initial_facing(player)
            for c, pt in enumerate(back_row_types):
                self.grid[back_r][c].stack.append(Piece(pt, player, facing))
            for c in range(SIZE):
                self.grid[pawn_r][c].stack.append(Piece(PieceType.BINH, player, facing))

    def find_king(self, player: Player) -> Optional[Tuple[int, int]]:
        """Locates the position (row, col) of the specified player's King (Vuong)."""
        for r in range(SIZE):
            for c in range(SIZE):
                sq = self.grid[r][c]
                if not sq.is_empty and sq.top.owner is player and sq.top.ptype is PieceType.VUONG:
                    return (r, c)
        return None

    def clone(self) -> "Board":
        """Creates an independent copy of the mutable board state."""
        b = Board.__new__(Board)
        b.grid = [[sq.copy() for sq in row] for row in self.grid]
        b.prisoners = {k: list(v) for k, v in self.prisoners.items()}
        b.reserve = {k: list(v) for k, v in self.reserve.items()}
        return b