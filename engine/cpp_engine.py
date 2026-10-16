"""Python <-> C++ engine bridge primitives for ColongphuongGUI.

Step 3.1 deliberately keeps this module independent from PyQt.  It owns the
wire-format conversion (Python Board <-> CLP1) and parsing of the C++ CLI
output/canonical moves.  GUI process management lives in gui/engine_controller.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Dict, Iterable, List, Optional

from .board import Board, SIZE
from .pieces import PIECE_CODE, PieceType, Player
from .rules import Move


_PIECE_ORDER = (
    PieceType.VUONG,
    PieceType.TUONG,
    PieceType.SI,
    PieceType.KI,
    PieceType.XA,
    PieceType.LONG,
    PieceType.PHUONG,
    PieceType.BINH,
)
_CODE_TO_PIECE = {code: ptype for ptype, code in PIECE_CODE.items()}
_KIND_FROM_CPP = {"R": "rotate", "S": "single", "T": "team", "D": "drop"}


@dataclass(frozen=True)
class EngineInfo:
    depth: int
    score_kind: str  # "cp" or "mate"
    score: int
    nodes: int
    time_ms: int
    nps: int
    pv: tuple[str, ...]

    @property
    def score_text(self) -> str:
        if self.score_kind == "mate":
            return f"mate {self.score}"
        return f"{self.score:+d}"


@dataclass(frozen=True)
class SyncSearchResult:
    bestmove_text: Optional[str]
    bestmove: Optional[Move]
    infos: tuple[EngineInfo, ...]
    stdout: str
    stderr: str


def _encode_hand(piece_types: Iterable[PieceType]) -> str:
    counts: Dict[PieceType, int] = {ptype: 0 for ptype in _PIECE_ORDER}
    for ptype in piece_types:
        counts[ptype] += 1
    out = "".join(PIECE_CODE[ptype] * counts[ptype] for ptype in _PIECE_ORDER)
    return out or "-"


def serialize_position(board: Board, player_to_move: Player) -> str:
    """Serialize a Python position to the exact CLP1 format used by C++."""
    side = "C" if player_to_move is Player.CAM else "X"
    cells: List[str] = []

    for r in range(SIZE):
        for c in range(SIZE):
            stack = board.sq(r, c).stack
            if not stack:
                cells.append("-")
                continue
            tokens = []
            for piece in stack:  # Python and C++ both store bottom -> top.
                owner = "C" if piece.owner is Player.CAM else "X"
                tokens.append(f"{owner}{PIECE_CODE[piece.ptype]}{piece.facing % 4}")
            cells.append(".".join(tokens))

    fields = [
        side,
        ",".join(cells),
        _encode_hand(board.reserve[Player.CAM]),
        _encode_hand(board.reserve[Player.XANH]),
        _encode_hand(board.prisoners[Player.CAM]),
        _encode_hand(board.prisoners[Player.XANH]),
    ]
    return "|".join(fields)


def _parse_square(token: str):
    if token == "--":
        return None
    if len(token) != 2 or not token.isdigit():
        raise ValueError(f"Invalid canonical square: {token!r}")
    r, c = int(token[0]), int(token[1])
    if not (0 <= r < SIZE and 0 <= c < SIZE):
        raise ValueError(f"Canonical square out of range: {token!r}")
    return (r, c)


def parse_canonical_move(text: str) -> Move:
    """Convert C++ canonical move, e.g. ``D:--:13:L:2:0``, to Python Move."""
    parts = text.strip().split(":")
    if len(parts) != 6:
        raise ValueError(f"Invalid canonical move: {text!r}")

    kind_code, src_text, dst_text, ptype_code, facing_text, rotate_text = parts
    if kind_code not in _KIND_FROM_CPP:
        raise ValueError(f"Unknown move kind: {kind_code!r}")
    if ptype_code not in _CODE_TO_PIECE:
        raise ValueError(f"Unknown piece code: {ptype_code!r}")

    facing_raw = int(facing_text)
    return Move(
        kind=_KIND_FROM_CPP[kind_code],
        src=_parse_square(src_text),
        dst=_parse_square(dst_text),
        ptype=_CODE_TO_PIECE[ptype_code],
        facing=None if facing_raw < 0 else facing_raw,
        rotate_after=int(rotate_text),
    )


def canonical_move_text(move: Move) -> str:
    """Python-side canonical encoder used by tests and diagnostics."""
    kind = {"rotate": "R", "single": "S", "team": "T", "drop": "D"}[move.kind]

    def sq(value):
        return "--" if value is None else f"{value[0]}{value[1]}"

    ptype = PIECE_CODE[move.ptype] if move.ptype is not None else "?"
    facing = -1 if move.facing is None else int(move.facing)
    return f"{kind}:{sq(move.src)}:{sq(move.dst)}:{ptype}:{facing}:{int(move.rotate_after)}"


def parse_info_line(line: str) -> Optional[EngineInfo]:
    """Parse one ``info ...`` line produced by clp_core_cli."""
    tokens = line.strip().split()
    if not tokens or tokens[0] != "info":
        return None

    try:
        depth_i = tokens.index("depth")
        score_i = tokens.index("score")
        nodes_i = tokens.index("nodes")
        time_i = tokens.index("time")
        nps_i = tokens.index("nps")
        pv_i = tokens.index("pv")

        score_kind = tokens[score_i + 1]
        if score_kind not in ("cp", "mate"):
            return None
        return EngineInfo(
            depth=int(tokens[depth_i + 1]),
            score_kind=score_kind,
            score=int(tokens[score_i + 2]),
            nodes=int(tokens[nodes_i + 1]),
            time_ms=int(tokens[time_i + 1]),
            nps=int(tokens[nps_i + 1]),
            pv=tuple(tokens[pv_i + 1 :]),
        )
    except (ValueError, IndexError):
        return None


def parse_bestmove_line(line: str) -> tuple[Optional[str], Optional[Move]]:
    line = line.strip()
    if not line.startswith("bestmove "):
        return None, None
    payload = line[len("bestmove ") :].strip()
    if payload == "none":
        return "none", None
    return payload, parse_canonical_move(payload)


def default_engine_path(project_root: Optional[Path] = None) -> Path:
    if project_root is None:
        project_root = Path(__file__).resolve().parents[1]
    return project_root / "clp_engine" / "build" / "Release" / "clp_core_cli.exe"


def run_search_sync(
    engine_path: Path | str,
    board: Board,
    player_to_move: Player,
    move_time_ms: int = 250,
    timeout_s: Optional[float] = None,
) -> SyncSearchResult:
    """Small synchronous helper for tests/tools. GUI code must use QProcess instead."""
    engine_path = Path(engine_path)
    state = serialize_position(board, player_to_move)
    if timeout_s is None:
        timeout_s = max(5.0, move_time_ms / 1000.0 + 3.0)

    cp = subprocess.run(
        [str(engine_path), "--search-time", str(int(move_time_ms)), state],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            f"C++ engine exited with code {cp.returncode}: {cp.stderr.strip() or cp.stdout.strip()}"
        )

    infos: List[EngineInfo] = []
    best_text: Optional[str] = None
    best_move: Optional[Move] = None
    for line in cp.stdout.splitlines():
        info = parse_info_line(line)
        if info is not None:
            infos.append(info)
            continue
        text_value, move_value = parse_bestmove_line(line)
        if text_value is not None:
            best_text, best_move = text_value, move_value

    if best_text is None:
        raise RuntimeError("C++ engine produced no bestmove line")

    return SyncSearchResult(
        bestmove_text=best_text,
        bestmove=best_move,
        infos=tuple(infos),
        stdout=cp.stdout,
        stderr=cp.stderr,
    )
