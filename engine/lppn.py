"""LPPN v0.2 candidate position codec for python-CLP.

Candidate specification: CAM=uppercase, XANH=lowercase is approved; rest awaits review.
It preserves board pieces, bottom-to-top stacks, owner, explicit facing, side
of play, reserve/prisoner multisets and a separately provided ply counter.
It does NOT encode repetition history, move tree, game outcome or comments.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from engine.board import Board, SIZE
from engine.pieces import Piece, PieceType, Player, PIECE_CODE


MAGIC = "lppn1"  # wire version unchanged; v0.2 is validation/spec revision
MAX_TEXT_LENGTH = 8192
MAX_STACK = 38
CODE_TO_TYPE = {code: piece_type for piece_type, code in PIECE_CODE.items()}
CANONICAL_TYPES = tuple(PieceType)


class LPPNError(ValueError):
    """Position encoding or decoding error."""


@dataclass(frozen=True)
class LPPNPosition:
    board: Board
    turn: Player
    ply: int


def _ensure_ply(ply: int) -> None:
    if type(ply) is not int or not 0 <= ply <= 1_000_000:
        raise LPPNError("ply must be an integer from 0 to 1000000")


def _piece_token(piece: Piece) -> str:
    if not isinstance(piece, Piece) or not isinstance(piece.ptype, PieceType) or not isinstance(piece.owner, Player):
        raise LPPNError("invalid Piece object")
    if type(piece.facing) is not int or piece.facing not in range(4):
        raise LPPNError("piece facing must be 0..3")
    letter = PIECE_CODE[piece.ptype]
    return (letter if piece.owner is Player.CAM else letter.lower()) + str(piece.facing)


def _validate_board(board: Board, strict: bool) -> None:
    if not isinstance(board, Board) or len(board.grid) != SIZE or any(len(row) != SIZE for row in board.grid):
        raise LPPNError("expected Board with 9x9 grid")
    kings = Counter()
    total = 0
    for row in board.grid:
        for sq in row:
            if not hasattr(sq, "stack") or not isinstance(sq.stack, list):
                raise LPPNError("each square must contain a stack list")
            st = sq.stack
            if len(st) > MAX_STACK:
                raise LPPNError("stack exceeds 38 pieces")
            if st:
                _piece_token(st[0])
                owner = st[0].owner
                for piece in st:
                    _piece_token(piece)
                    if piece.owner is not owner:
                        raise LPPNError("mixed-owner stack")
                    if piece.ptype is PieceType.VUONG:
                        kings[piece.owner] += 1
                if len(st) > 1 and any(p.ptype is PieceType.VUONG for p in st):
                    raise LPPNError("VUONG cannot belong to a stack")
                total += len(st)
    for field in ("reserve", "prisoners"):
        hands = getattr(board, field, None)
        if not isinstance(hands, dict) or set(hands) != set(Player):
            raise LPPNError(f"{field} must contain CAM and XANH")
        for owner in Player:
            types = hands[owner]
            if not isinstance(types, list):
                raise LPPNError(f"{field}: hand must be a list")
            for ptype in types:
                if not isinstance(ptype, PieceType) or ptype is PieceType.VUONG:
                    raise LPPNError("hand type invalid or contains VUONG")
                if field == "reserve" and ptype not in (PieceType.LONG, PieceType.PHUONG):
                    raise LPPNError("reserve permits LONG/PHUONG only")
            if field == "reserve" and len(set(types)) != len(types):
                raise LPPNError("duplicate reserve piece")
            total += len(types)
    if strict:
        if kings[Player.CAM] != 1 or kings[Player.XANH] != 1:
            raise LPPNError("strict play requires exactly one VUONG per side")
        if total > 40:
            raise LPPNError("more than 40 pieces in position")


def _hand_text(hands: dict) -> str:
    def one(player: Player) -> str:
        counts = Counter(hands[player])
        text = "".join(PIECE_CODE[ptype] * counts[ptype] for ptype in CANONICAL_TYPES)
        return text or "-"
    return one(Player.CAM) + "/" + one(Player.XANH)


def to_lppn(board: Board, turn: Player, *, ply: int = 0, strict: bool = False) -> str:
    """Serialize a CLP Board to canonical LPPN (wire format lppn1) (editor-friendly by default)."""
    if not isinstance(turn, Player):
        raise LPPNError("turn must be Player.CAM or Player.XANH")
    _ensure_ply(ply)
    _validate_board(board, strict)
    rows = []
    for row in board.grid:
        parts = []
        empty = 0
        for sq in row:
            stack = sq.stack
            if not stack:
                empty += 1
                continue
            if empty:
                parts.append(str(empty))
                empty = 0
            parts.append(
                _piece_token(stack[0]) if len(stack) == 1
                else "[" + "".join(_piece_token(piece) for piece in stack) + "]"
            )
        if empty:
            parts.append(str(empty))
        rows.append("".join(parts))
    side = "c" if turn is Player.CAM else "x"
    result = f"{MAGIC} {'/'.join(rows)} {side} {_hand_text(board.reserve)} {_hand_text(board.prisoners)} {ply}"
    if len(result) > MAX_TEXT_LENGTH:
        raise LPPNError("encoded LPPN exceeds 8192 characters")
    return result


def _decode_pair(pair: str) -> Piece:
    if len(pair) != 2 or pair[1] not in "0123" or pair[0].upper() not in CODE_TO_TYPE or not pair[0].isascii():
        raise LPPNError(f"invalid piece token: {pair!r}")
    side = Player.CAM if pair[0].isupper() else Player.XANH
    return Piece(CODE_TO_TYPE[pair[0].upper()], side, int(pair[1]))


def _parse_row(row: str, row_index: int, board: Board) -> None:
    col = 0
    i = 0
    while i < len(row):
        ch = row[i]
        if ch in "123456789":
            col += int(ch)
            i += 1
        elif ch == "[":
            end = row.find("]", i + 1)
            if end < 0:
                raise LPPNError(f"row {row_index}: unterminated stack")
            raw = row[i + 1:end]
            if len(raw) < 4 or len(raw) % 2:
                raise LPPNError(f"row {row_index}: stack must contain at least two pieces")
            pieces = [_decode_pair(raw[j:j+2]) for j in range(0, len(raw), 2)]
            if col >= SIZE:
                raise LPPNError(f"row {row_index}: too many squares")
            board.sq(row_index, col).stack = pieces
            col += 1
            i = end + 1
        else:
            if i + 2 > len(row) or col >= SIZE:
                raise LPPNError(f"row {row_index}: truncated token or too many squares")
            board.sq(row_index, col).stack = [_decode_pair(row[i:i+2])]
            col += 1
            i += 2
        if col > SIZE:
            raise LPPNError(f"row {row_index}: exceeds 9 squares")
    if col != SIZE:
        raise LPPNError(f"row {row_index}: {col} squares, expected 9")


def _parse_hands(text: str, field: str) -> dict[Player, list[PieceType]]:
    halves = text.split("/")
    if len(halves) != 2:
        raise LPPNError(f"{field}: expected CAM/XANH")
    out: dict[Player, list[PieceType]] = {}
    for owner, chars in zip(Player, halves):
        if chars == "-":
            out[owner] = []
            continue
        if not chars:
            raise LPPNError(f"{field}: empty hand needs '-' placeholder")
        items = []
        for ch in chars:
            if ch not in CODE_TO_TYPE or ch == "V":
                raise LPPNError(f"{field}: invalid hand piece {ch!r}")
            items.append(CODE_TO_TYPE[ch])
        out[owner] = items
    return out


def from_lppn(text: str, *, strict: bool = False) -> LPPNPosition:
    """Parse LPPN into a new independent CLP Board, side and ply counter."""
    if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
        raise LPPNError("LPPN must be text with length <= 8192")
    fields = text.split()
    if len(fields) != 6 or fields[0] != MAGIC:
        raise LPPNError("expected: lppn1 BOARD TURN RESERVE PRISONERS PLY")
    _, encoded_board, side_text, reserve_text, prisoners_text, ply_text = fields
    if side_text not in ("c", "x"):
        raise LPPNError("turn must be c or x")
    if not ply_text.isascii() or not ply_text.isdecimal() or (len(ply_text) > 1 and ply_text[0] == "0"):
        raise LPPNError("invalid ply number")
    ply = int(ply_text)
    _ensure_ply(ply)
    rows = encoded_board.split("/")
    if len(rows) != SIZE:
        raise LPPNError("board must have exactly nine '/'-separated rows")
    board = Board()
    board.reserve = _parse_hands(reserve_text, "reserve")
    board.prisoners = _parse_hands(prisoners_text, "prisoners")
    for row_index, row in enumerate(rows):
        _parse_row(row, row_index, board)
    _validate_board(board, strict)
    return LPPNPosition(board=board, turn=Player.CAM if side_text == "c" else Player.XANH, ply=ply)


def normalize_lppn(text: str, *, strict: bool = False) -> str:
    """Parse and re-emit a canonical string. Rejects invalid grammar or state."""
    decoded = from_lppn(text, strict=strict)
    return to_lppn(decoded.board, decoded.turn, ply=decoded.ply, strict=strict)
