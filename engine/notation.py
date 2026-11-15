import json
import os
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Iterable

from engine.board import Board
from engine.game import Game, MoveNode, _position_hash
from engine.pieces import Piece, PieceType, Player, PIECE_CODE, NON_ROTATABLE, initial_facing
import engine.rules as rules
from engine.rules import Move

ROWS = "abcdefghi"
COLS = "987654321"
DIR_MAP = {"^": 0, "˄": 0, ">": 1, "v": 2, "V": 2, "˅": 2, "<": 3}
DIR_SYMBOLS = {0: "^", 1: ">", 2: "v", 3: "<"}
FULLWIDTH_COLS = "  ９ ８ ７ ６ ５ ４ ３ ２ １"

HEADER_KEYS = {
    "Tên Phòng:": "room_name",
    "Ngày Giờ Chơi:": "date",
    "Ngày Giờ Lưu:": "save_date",
    "Kỳ Thủ Thắng:": "winner",
    "Kỳ Thủ Cầm Cam:": "player_cam",
    "Kỳ Thủ Cầm Xanh:": "player_xanh",
}

POSITION_PREFIX = "#position "
COMPAT_LEGACY_TURNABOUT = "legacy-turnabout=1"

_BRANCH_HEADER_PATTERN = re.compile(
    r"^\s*(?:nhánh|nhanh)\s*:\s*(?:nước|nuoc)\s*(?:thứ|thu)?\s*(\d+)",
    re.IGNORECASE,
)

# One normalized numbered move, used by both modern LPGF and legacy TXT.
# Supports 1.P*b7, 5.Sb8(a8), 9.Bd8.d9(c8), 17.Bc2<(c3), 19.[B]c6>(c6), 40.L=(c5)
_MOVE_PATTERN = re.compile(
    r"^\s*(\d+)(?:[\.\s]\s*|\s+)(?:(Resign|Xin\s*thua|Xin\s*hàng|Xin\s*hang)|"
    r"(?:(\[?)([VTSKXLBP])\]?(\*?)([a-i][1-9]|=)([>^<˅˄vV]?)(?:\.([a-i][1-9]))?(?:\(([a-i][1-9])\))?))\s*$",
    re.IGNORECASE,
)

_TXT_MOVE_BODY_PATTERN = re.compile(
    r"(?:(?:Resign|Xin\s*thua|Xin\s*hàng|Xin\s*hang)|#|"
    r"(?:\[[VTSKXLBP]\]|[VTSKXLBP])\*?(?:[a-i][1-9]|=)"
    r"[>^<˅˄vV]?(?:\.[a-i][1-9])?(?:\([a-i][1-9]\))?)",
    re.IGNORECASE,
)


class IllegalRecordMoveError(ValueError):
    """Raised when an illegal, ambiguous, or invalid move is encountered in a record."""
    def __init__(
        self,
        message: str,
        *,
        move_no: int = 0,
        move_text: str = "",
        game: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        applied_moves: int = 0,
    ):
        super().__init__(message)
        self.move_no = move_no
        self.move_text = move_text
        self.game = game
        self.metadata = metadata or {}
        self.applied_moves = applied_moves


def pos_to_sq(pos: Tuple[int, int]) -> str:
    """Converts a (row, col) matrix index to board notation (e.g., (0, 8) -> 'a1')."""
    return f"{ROWS[pos[0]]}{COLS[pos[1]]}"


def sq_to_pos(sq_str: str) -> Optional[Tuple[int, int]]:
    """Converts board notation (e.g., 'a1') to a (row, col) matrix index."""
    if len(sq_str) < 2 or sq_str[0].lower() not in ROWS or sq_str[1] not in COLS:
        return None
    return ROWS.index(sq_str[0].lower()), COLS.index(sq_str[1])


def strip_source_square(notation: str) -> str:
    """Strips parenthesized source square (e.g. 'Sb8(a8)' -> 'Sb8', '19.[B]c6>(c6)' -> '19.[B]c6>')."""
    return re.sub(r"\([a-i][1-9]\)$", "", notation.strip())


def detect_ascii_board(text: str) -> bool:
    """Detects whether text contains a 9x9 ASCII CLP board diagram."""
    return bool(re.search(r"\+[-]{27}\+", text) and re.search(r"\|\s*.*?\s*\|[a-i]", text, re.IGNORECASE))


def format_ascii_board(board: Board, turn: Player, base_ply: int = 0) -> str:
    """Formats a CLP Board, turn, and starting ply into standard 9x9 ASCII board diagram."""
    def format_piece(p: Piece) -> str:
        code = PIECE_CODE[p.ptype]
        prefix = "c" if p.owner == Player.CAM else ""
        default_f = 2 if p.owner == Player.CAM else 0
        can_rot = p.ptype not in NON_ROTATABLE
        facing_sym = ""
        if can_rot and (p.facing % 4) != default_f:
            facing_sym = DIR_SYMBOLS[p.facing % 4]
        return f"{prefix}{code}{facing_sym}"

    def format_cell(sq) -> str:
        if sq.is_empty:
            return "∗"
        if len(sq.stack) == 1:
            return format_piece(sq.top)
        inner = "".join(format_piece(p) for p in sq.stack)
        return f"[{inner}]"

    def format_hand(hand_pieces: list) -> str:
        if not hand_pieces:
            return "không"
        counts: Dict[PieceType, int] = {}
        for pt in hand_pieces:
            counts[pt] = counts.get(pt, 0) + 1
        order = [
            PieceType.BINH,
            PieceType.KI,
            PieceType.XA,
            PieceType.SI,
            PieceType.TUONG,
            PieceType.LONG,
            PieceType.PHUONG,
            PieceType.VUONG,
        ]
        parts = []
        for pt in sorted(counts.keys(), key=lambda x: order.index(x) if x in order else 99):
            c = counts[pt]
            code = PIECE_CODE[pt]
            parts.append(f"{code}{c}" if c > 1 else f"{code}")
        return " ".join(parts)

    lines = []
    cam_hand = board.prisoners[Player.CAM] + board.reserve[Player.CAM]
    lines.append(f"Cam: {format_hand(cam_hand)}")
    lines.append(FULLWIDTH_COLS)
    lines.append("+---------------------------+")
    for r in range(9):
        cells = [format_cell(board.sq(r, c)) for c in range(9)]
        row_str = " ".join(cells)
        lines.append(f"| {row_str}|{ROWS[r]}")
    lines.append("+---------------------------+")
    xanh_hand = board.prisoners[Player.XANH] + board.reserve[Player.XANH]
    lines.append(f"Xanh: {format_hand(xanh_hand)}")
    turn_str = "Cam" if turn == Player.CAM else "Xanh"
    lines.append(f"Lượt đi: {turn_str}")
    if base_ply > 0:
        lines.append(f"{base_ply} ...")
    return "\n".join(lines)


def parse_ascii_board(text: str) -> Optional[Tuple[Board, Player, int]]:
    """Parses a 9x9 ASCII CLP board diagram into (Board, Player, base_ply)."""
    if not detect_ascii_board(text):
        return None

    code_to_ptype = {
        "V": PieceType.VUONG,
        "T": PieceType.TUONG,
        "S": PieceType.SI,
        "K": PieceType.KI,
        "X": PieceType.XA,
        "L": PieceType.LONG,
        "P": PieceType.PHUONG,
        "B": PieceType.BINH,
    }

    board = Board()
    board.reserve = {Player.CAM: [], Player.XANH: []}
    board.prisoners = {Player.CAM: [], Player.XANH: []}
    turn = Player.CAM
    base_ply = 0

    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # 1. Cam hand
    m_cam = re.search(r"Cam\s*:\s*(.*)", text, re.IGNORECASE)
    if m_cam:
        raw = m_cam.group(1).strip()
        if raw.lower() != "không":
            for token in raw.split():
                m_t = re.match(r"([VLPTSKXB])(\d*)", token, re.IGNORECASE)
                if m_t:
                    code, cnt_s = m_t.groups()
                    cnt = int(cnt_s) if cnt_s else 1
                    pt = code_to_ptype[code.upper()]
                    board.prisoners[Player.CAM].extend([pt] * cnt)

    # 2. Rows
    row_pattern = re.compile(r"^\|\s*(.*?)\s*\|([a-i])\s*$", re.IGNORECASE)
    piece_pattern = re.compile(r"(c?)([VLPTSKXB])([>^v<]?)", re.IGNORECASE)
    row_map = {ch: i for i, ch in enumerate(ROWS)}

    for line in lines:
        m_r = row_pattern.match(line)
        if m_r:
            content_str, r_ch = m_r.groups()
            r_idx = row_map[r_ch.lower()]
            tokens = content_str.split()
            if len(tokens) != 9:
                continue
            for c_idx, tok in enumerate(tokens):
                if tok in ("∗", "*", "."):
                    continue
                if tok.startswith("[") and tok.endswith("]"):
                    inner = tok[1:-1]
                    matches = piece_pattern.findall(inner)
                    for c_prefix, pcode, f_sym in matches:
                        owner = Player.CAM if c_prefix.lower() == "c" else Player.XANH
                        pt = code_to_ptype[pcode.upper()]
                        default_f = 2 if owner == Player.CAM else 0
                        facing = DIR_MAP[f_sym] if f_sym else default_f
                        board.sq(r_idx, c_idx).stack.append(Piece(pt, owner, facing))
                else:
                    m_p = re.match(r"^(c?)([VLPTSKXB])([>^v<]?)$", tok, re.IGNORECASE)
                    if m_p:
                        c_prefix, pcode, f_sym = m_p.groups()
                        owner = Player.CAM if c_prefix.lower() == "c" else Player.XANH
                        pt = code_to_ptype[pcode.upper()]
                        default_f = 2 if owner == Player.CAM else 0
                        facing = DIR_MAP[f_sym] if f_sym else default_f
                        board.sq(r_idx, c_idx).stack.append(Piece(pt, owner, facing))

    # 3. Xanh hand
    m_xanh = re.search(r"Xanh\s*:\s*(.*)", text, re.IGNORECASE)
    if m_xanh:
        raw = m_xanh.group(1).strip()
        if raw.lower() != "không":
            for token in raw.split():
                m_t = re.match(r"([VLPTSKXB])(\d*)", token, re.IGNORECASE)
                if m_t:
                    code, cnt_s = m_t.groups()
                    cnt = int(cnt_s) if cnt_s else 1
                    pt = code_to_ptype[code.upper()]
                    board.prisoners[Player.XANH].extend([pt] * cnt)

    # 4. Turn
    m_turn = re.search(r"Lượt\s*đi\s*:\s*(Cam|Xanh)", text, re.IGNORECASE)
    if m_turn:
        turn = Player.CAM if m_turn.group(1).lower() == "cam" else Player.XANH

    # 5. Ply
    m_ply = re.search(r"(\d+)\s*\.\.\.", text)
    if m_ply:
        base_ply = int(m_ply.group(1))

    return board, turn, base_ply


def _extract_branch_blocks(content: str) -> Tuple[str, List[Tuple[int, List[str]]]]:
    """Separates mainline text from branch blocks labeled 'nhánh: nước thứ N'."""
    lines = content.splitlines()
    mainline_lines: List[str] = []
    branches: List[Tuple[int, List[str]]] = []

    curr_branch_ply: Optional[int] = None
    curr_branch_lines: List[str] = []

    for line in lines:
        m_br = _BRANCH_HEADER_PATTERN.match(line)
        if m_br:
            if curr_branch_ply is not None:
                branches.append((curr_branch_ply, curr_branch_lines))
            curr_branch_ply = int(m_br.group(1))
            curr_branch_lines = []
            continue

        if curr_branch_ply is not None:
            curr_branch_lines.append(line)
        else:
            mainline_lines.append(line)

    if curr_branch_ply is not None:
        branches.append((curr_branch_ply, curr_branch_lines))

    return "\n".join(mainline_lines), branches


def _pseudo_legacy_compatible_moves(game: Game) -> List[Move]:
    """Return pseudo-legal moves plus compatibility-only 180° rotations for old records."""
    base_moves = [] if game.result is not None else list(rules.generate_moves(game.board, game.current))
    out = list(base_moves)
    seen = {(m.kind, m.src, m.dst, m.ptype, m.facing, m.rotate_after) for m in out}
    added_rotate_src = set()

    for lm in base_moves:
        if lm.ptype in NON_ROTATABLE:
            continue

        if lm.kind in ("single", "team") and lm.rotate_after == 0:
            extra = Move(
                kind=lm.kind,
                src=lm.src,
                dst=lm.dst,
                ptype=lm.ptype,
                facing=lm.facing,
                rotate_after=2,
            )
            key = (extra.kind, extra.src, extra.dst, extra.ptype, extra.facing, extra.rotate_after)
            if key not in seen:
                out.append(extra)
                seen.add(key)

        if lm.kind == "rotate" and lm.src not in added_rotate_src:
            extra = Move(kind="rotate", src=lm.src, ptype=lm.ptype, rotate_after=2)
            key = (extra.kind, extra.src, extra.dst, extra.ptype, extra.facing, extra.rotate_after)
            if key not in seen:
                out.append(extra)
                seen.add(key)
            added_rotate_src.add(lm.src)

    return out


def _legacy_compatible_moves(game: Game) -> List[Move]:
    return [m for m in _pseudo_legacy_compatible_moves(game) if _record_candidate_is_legal(game, m)]


def _record_candidate_is_legal(game: Game, move: Move) -> bool:
    try:
        b2 = game.board.clone()
        rules.apply_move(b2, game.current, move)
        return not rules.is_in_check(b2, game.current)
    except (ValueError, IndexError):
        return False


def _commit_loaded_move(game: Game, move: Move, notation_text: str, *, bypass_validate: bool = False) -> bool:
    return game.commit_prevalidated_move(
        move,
        notation_text=notation_text,
        check_terminal=False,
    )


def _base_position_payload(board: Board, current: Player) -> Dict[str, Any]:
    squares = []
    for r in range(9):
        for c in range(9):
            stack = board.sq(r, c).stack
            if not stack:
                continue
            squares.append([
                r,
                c,
                [[p.ptype.name, p.owner.name, int(p.facing) % 4] for p in stack],
            ])

    return {
        "current": current.name,
        "squares": squares,
        "reserve": {
            pl.name: [ptype.name for ptype in board.reserve[pl]]
            for pl in Player
        },
        "prisoners": {
            pl.name: [ptype.name for ptype in board.prisoners[pl]]
            for pl in Player
        },
    }


def _board_from_base_payload(payload: Dict[str, Any]) -> Tuple[Board, Player]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid #position payload")

    try:
        current = Player[payload["current"]]
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid player in #position payload") from exc

    board = Board()
    board.reserve = {Player.CAM: [], Player.XANH: []}
    board.prisoners = {Player.CAM: [], Player.XANH: []}

    try:
        squares = payload.get("squares", [])
        for entry in squares:
            r, c, pieces = entry
            r, c = int(r), int(c)
            if not Board.in_bounds(r, c):
                raise ValueError(f"Invalid square in #position: {(r, c)}")
            stack = []
            for ptype_name, owner_name, facing in pieces:
                stack.append(Piece(PieceType[ptype_name], Player[owner_name], int(facing) % 4))
            board.sq(r, c).stack = stack

        for pl in Player:
            board.reserve[pl] = [PieceType[name] for name in payload.get("reserve", {}).get(pl.name, [])]
            board.prisoners[pl] = [PieceType[name] for name in payload.get("prisoners", {}).get(pl.name, [])]
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Invalid square"):
            raise
        raise ValueError("Invalid piece data in #position payload") from exc

    return board, current


def resolve_record_move_candidates(
    candidates: Iterable[Move],
    *,
    src_pos: Optional[Tuple[int, int]],
    dst_pos: Tuple[int, int],
) -> Optional[Move]:
    unique: List[Move] = []
    seen = set()
    for mv in candidates:
        key = (mv.kind, mv.src, mv.dst, mv.ptype, mv.facing, mv.rotate_after % 4)
        if key in seen:
            continue
        seen.add(key)
        unique.append(mv)

    if not unique:
        return None

    if src_pos is not None:
        exact = [mv for mv in unique if mv.src == src_pos]
        return exact[0] if len(exact) == 1 else None

    rotations = [
        mv for mv in unique
        if mv.kind == "rotate" and mv.src == dst_pos
    ]
    if len(rotations) == 1:
        return rotations[0]
    if rotations:
        return None

    sources = {mv.src for mv in unique}
    if len(sources) == 1 and len(unique) == 1:
        return unique[0]

    return None


class LPGFNotation:
    """Handles serialization and parsing of .lpgf (v1.1 & v2.0) and historical .txt record files."""

    @staticmethod
    def export_lpgf(
        game: Game,
        player_cam: str = "",
        player_xanh: str = "",
        save_time: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        version: str = "2.0",
    ) -> str:
        """Serialize the game tree into LPGF 2.0 (default) or legacy LPGF 1.1."""
        save_time = save_time or datetime.now()
        meta = metadata or getattr(game, "metadata", {}) or {}
        name_cam = (player_cam or meta.get("player_cam") or "").strip()
        name_xanh = (player_xanh or meta.get("player_xanh") or "").strip()
        display_cam = name_cam or "Cam"
        display_xanh = name_xanh or "Xanh"
        room = meta.get("room_name") or meta.get("room") or "Phòng tập luyện"
        play_date = meta.get("play_time") or meta.get("date") or save_time.strftime("%d-%m-%Y %H:%M")

        # Collect active mainline
        path: List[MoveNode] = []
        curr = game.current_node
        while curr and curr.parent is not None:
            path.append(curr)
            curr = curr.parent
        path.reverse()
        curr = game.current_node
        while curr and curr.children:
            curr = curr.children[0]
            path.append(curr)

        winner_str = meta.get("winner") or "Chưa kết thúc"
        last_node = path[-1] if path else game.current_node
        res = getattr(last_node, "result", None) or game.result
        if res:
            res_lower = res.lower()
            winner_side = None
            if "cam thang" in res_lower:
                winner_side = Player.CAM
            elif "xanh thang" in res_lower:
                winner_side = Player.XANH
            elif res_lower.startswith("cam thua") or res_lower.startswith("cam xin thua"):
                winner_side = Player.XANH
            elif res_lower.startswith("xanh thua") or res_lower.startswith("xanh xin thua"):
                winner_side = Player.CAM

            if winner_side is Player.CAM:
                winner_str = f"{name_cam}(Cam) Thắng" if name_cam else "Cam Thắng"
            elif winner_side is Player.XANH:
                winner_str = f"{name_xanh}(Xanh) Thắng" if name_xanh else "Xanh Thắng"
            else:
                winner_str = res

        has_custom_root = game.has_custom_base_position()
        base_board, base_current = game.get_base_position()

        if str(version).startswith("1"):
            # Legacy LPGF 1.1 export
            lines = ["#lpgf version=1.1 encoding=UTF-8"]
            if has_custom_root:
                payload = _base_position_payload(base_board, base_current)
                lines.append(POSITION_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            if meta.get("legacy_turnabout", False):
                lines.append(f"#compat {COMPAT_LEGACY_TURNABOUT}")
            if meta.get("source"):
                lines.append(f"#source {meta['source']}")

            lines.extend([
                f"Tên Phòng: {room}",
                f"Ngày Giờ Chơi: {play_date}",
                f"Ngày Giờ Lưu: {save_time.strftime('%d-%m-%Y %H:%M')}",
                f"Kỳ Thủ Thắng: {winner_str}",
                f"Kỳ Thủ Cầm Cam: {display_cam}",
                f"Kỳ Thủ Cầm Xanh: {display_xanh}",
                "",
            ])

            sim_board, sim_current = game.get_base_position()
            for idx, node in enumerate(path, 1):
                if not node.move:
                    continue
                notation_text = node.notation_text or node.move.notation(sim_board)
                lines.append(f"{idx}.{notation_text}")
                rules.apply_move(sim_board, sim_current, node.move)
                sim_current = rules.other(sim_current)

            if res:
                res_lower = res.lower()
                if "chieu het" in res_lower or "checkmate" in res_lower or "#" in res_lower:
                    lines.append(f"{len(path) + 1}.#")
                elif any(k in res_lower for k in ("xin thua", "xin hang", "resign")):
                    lines.append(f"{len(path) + 1}.Xin thua")
            return "\n".join(lines).rstrip() + "\n"

        # Modern LPGF 2.0 export
        lines = [
            "#lpgf version=2.0 encoding=UTF-8",
            f"Tên Phòng: {room}",
            f"Ngày Giờ Chơi: {play_date}",
            f"Ngày Giờ Lưu: {save_time.strftime('%d-%m-%Y %H:%M')}",
            f"Kỳ Thủ Thắng: {winner_str}",
            f"Kỳ Thủ Cầm Cam: {display_cam}",
            f"Kỳ Thủ Cầm Xanh: {display_xanh}",
            "",
        ]

        if has_custom_root:
            lines.append(format_ascii_board(base_board, base_current, getattr(game, "base_ply", 0)))
            lines.append("")

        sim_board, sim_current = game.get_base_position()
        for idx, node in enumerate(path, 1):
            if not node.move:
                continue
            clean = strip_source_square(node.notation_text or node.move.notation(sim_board))
            if node.move.kind != "drop" and node.move.rotate_after % 4 == 0 and node.move.kind != "rotate":
                clean = re.sub(r"([a-i][1-9]|=)[>^<˅˄vV](\.[a-i][1-9])?", r"\1\2", clean)

            if node.move.kind != "drop" and node.move.src:
                mv_str = f"{clean}({pos_to_sq(node.move.src)})"
            else:
                mv_str = clean
            lines.append(f"{idx}.{mv_str}")
            rules.apply_move(sim_board, sim_current, node.move)
            sim_current = rules.other(sim_current)

        if res:
            res_lower = res.lower()
            if "chieu het" in res_lower or "checkmate" in res_lower or "#" in res_lower:
                lines.append(f"{len(path) + 1}.#")
            elif any(k in res_lower for k in ("xin thua", "xin hang", "resign")):
                lines.append(f"{len(path) + 1}.Xin thua")

        # Variations (Biến nhánh)
        all_nodes = list(game.nodes())
        for node in all_nodes:
            if len(node.children) > 1:
                for br_child in node.children[1:]:
                    # Determine branch starting ply
                    b_ply = 1
                    curr_p = br_child
                    while curr_p.parent is not None:
                        b_ply += 1
                        curr_p = curr_p.parent
                    lines.append("")
                    lines.append(f"nhánh: nước thứ {b_ply - 1}")
                    curr_br = br_child
                    step_ply = b_ply - 1
                    while curr_br:
                        if curr_br.move:
                            b_clean = strip_source_square(curr_br.notation_text or curr_br.move.notation())
                            if curr_br.move.kind != "drop" and curr_br.move.src:
                                b_str = f"{b_clean}({pos_to_sq(curr_br.move.src)})"
                            else:
                                b_str = b_clean
                            lines.append(f"{step_ply} {b_str}")
                        step_ply += 1
                        curr_br = curr_br.children[0] if curr_br.children else None

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def export_txt(
        game: Game,
        player_cam: str = "",
        player_xanh: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        save_time: Optional[datetime] = None,
    ) -> str:
        """Exports the active line to standard Vietnamese tournament 6-column TXT format (matching 238 sample games)."""
        meta = metadata or getattr(game, "metadata", {}) or {}
        name_cam = (player_cam or meta.get("player_cam") or "").strip()
        name_xanh = (player_xanh or meta.get("player_xanh") or "").strip()
        display_cam = name_cam or "Cam"
        display_xanh = name_xanh or "Xanh"
        room = meta.get("room_name") or meta.get("room") or "Phòng tập luyện"
        play_date = meta.get("play_time") or meta.get("date") or (save_time or datetime.now()).strftime("%d-%m-%Y %H:%M")
        winner = meta.get("winner") or (game.result if game.result else "Chưa kết thúc")

        lines = [
            "Kỳ Phổ Game Đấu",
            f"Tên Phòng: {room}",
            f"Ngày Giờ Chơi: {play_date}",
            f"Kỳ Thủ Thắng: {winner}",
            f"Kỳ Thủ Cầm Cam: {display_cam}",
            f"Kỳ Thủ Cầm Xanh: {display_xanh}",
            "",
        ]

        has_custom_root = game.has_custom_base_position()
        base_board, base_current = game.get_base_position()
        if has_custom_root:
            lines.append(format_ascii_board(base_board, base_current, getattr(game, "base_ply", 0)))
            lines.append("")

        path: List[MoveNode] = []
        curr = game.current_node
        while curr and curr.parent is not None:
            path.append(curr)
            curr = curr.parent
        path.reverse()
        curr = game.current_node
        while curr and curr.children:
            curr = curr.children[0]
            path.append(curr)

        sim_board, sim_current = game.get_base_position()
        moves = []
        for idx, node in enumerate(path, 1):
            if not node.move:
                continue
            clean = strip_source_square(node.notation_text or node.move.notation(sim_board))
            if node.move.kind != "drop" and node.move.rotate_after % 4 == 0 and node.move.kind != "rotate":
                clean = re.sub(r"([a-i][1-9]|=)[>^<˅˄vV](\.[a-i][1-9])?", r"\1\2", clean)
            moves.append((idx, clean))
            rules.apply_move(sim_board, sim_current, node.move)
            sim_current = rules.other(sim_current)

        last_node = path[-1] if path else game.current_node
        res = getattr(last_node, "result", None) or game.result
        if res:
            res_lower = res.lower()
            if "chieu het" in res_lower or "checkmate" in res_lower or "#" in res_lower:
                moves.append((len(moves) + 1, "#"))
            elif any(k in res_lower for k in ("xin thua", "xin hang", "resign")):
                moves.append((len(moves) + 1, "Xin thua"))

        cols = 6
        for i in range(0, len(moves), cols):
            chunk = moves[i : i + cols]
            row_parts = []
            for move_num, mv in chunk:
                entry = f" {move_num}.{mv}" if move_num <= 9 else f"{move_num}.{mv}"
                row_parts.append(f"{entry:<18}")
            lines.append("".join(row_parts).rstrip())

        # Variations (Biến nhánh)
        all_nodes = list(game.nodes())
        for node in all_nodes:
            if len(node.children) > 1:
                for br_child in node.children[1:]:
                    b_ply = 1
                    curr_p = br_child
                    while curr_p.parent is not None:
                        b_ply += 1
                        curr_p = curr_p.parent
                    lines.append("")
                    lines.append(f"nhánh: nước thứ {b_ply - 1}")
                    br_moves = []
                    curr_br = br_child
                    step_ply = b_ply - 1
                    while curr_br:
                        if curr_br.move:
                            b_clean = strip_source_square(curr_br.notation_text or curr_br.move.notation())
                            if curr_br.move.kind != "drop" and curr_br.move.rotate_after % 4 == 0 and curr_br.move.kind != "rotate":
                                b_clean = re.sub(r"([a-i][1-9]|=)[>^<˅˄vV](\.[a-i][1-9])?", r"\1\2", b_clean)
                            br_moves.append((step_ply, b_clean))
                        step_ply += 1
                        curr_br = curr_br.children[0] if curr_br.children else None

                    for bi in range(0, len(br_moves), cols):
                        b_chunk = br_moves[bi : bi + cols]
                        b_parts = []
                        for m_n, m_v in b_chunk:
                            b_ent = f" {m_n}.{m_v}" if m_n <= 9 else f"{m_n}.{m_v}"
                            b_parts.append(f"{b_ent:<18}")
                        lines.append("".join(b_parts).rstrip())

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _metadata(content: str) -> Dict[str, Any]:
        metadata = {
            "version": "1.0",
            "room_name": "",
            "date": "",
            "save_date": "",
            "winner": "",
            "player_cam": "Cam",
            "player_xanh": "Xanh",
        }
        version_match = re.search(r"(?im)^#lpgf\s+version=([^\s]+)", content)
        if version_match:
            metadata["version"] = version_match.group(1)

        for line in content.splitlines():
            line_str = line.strip()
            for prefix, key in HEADER_KEYS.items():
                if line_str.startswith(prefix):
                    val = line_str.split(":", 1)[1].strip()
                    metadata[key] = val
                    if prefix == "Ngày Giờ Lưu:" and not metadata.get("date"):
                        metadata["date"] = val
                    break
        return metadata

    @staticmethod
    def _extract_base_position(content: str) -> Optional[Tuple[Board, Player]]:
        if detect_ascii_board(content):
            res = parse_ascii_board(content)
            if res:
                board, turn, base_ply = res
                return board, turn

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line.startswith(POSITION_PREFIX):
                raw_json = line[len(POSITION_PREFIX):].strip()
                try:
                    payload = json.loads(raw_json)
                except json.JSONDecodeError as exc:
                    raise ValueError("Invalid JSON in #position header") from exc
                return _board_from_base_payload(payload)
        return None

    @staticmethod
    def _has_legacy_compat_marker(content: str) -> bool:
        return any(
            line.strip().lower() == f"#compat {COMPAT_LEGACY_TURNABOUT}"
            for line in content.splitlines()
        )

    @staticmethod
    def _apply_numbered_moves(
        content: str,
        game: Game,
        numbered_moves: Iterable[str],
        *,
        allow_legacy_turnabout: bool = False,
        base_position: Optional[Tuple[Board, Player]] = None,
        legacy_txt_semantics: bool = False,
        allow_hash_mate: bool = False,
        branches: Optional[List[Tuple[int, List[str]]]] = None,
        truncate_on_illegal: bool = False,
    ) -> Dict[str, Any]:
        """Apply already separated numbered move strings and branch variations to ``game``."""
        metadata = LPGFNotation._metadata(content)
        if base_position is None:
            game.reset()
        else:
            board, player_to_move = base_position
            game.set_base_position(board, player_to_move)

        last_dst_pos = None
        expected_no = 1

        for raw_move in numbered_moves:
            line = raw_move.strip()
            if not line:
                continue

            hash_match = re.match(r"^\s*(\d+)\.\s*#\s*$", line)
            if hash_match:
                move_no = int(hash_match.group(1))
                if not allow_hash_mate:
                    if truncate_on_illegal:
                        metadata["truncated_illegal_move"] = raw_move
                        metadata["illegal_move_no"] = move_no
                        break
                    raise IllegalRecordMoveError(
                        f"Ký hiệu chiếu hết không hợp lệ tại nước {move_no}: {raw_move}",
                        move_no=move_no,
                        move_text=raw_move,
                        game=game,
                        metadata=metadata,
                        applied_moves=len(list(game.nodes())) - 1,
                    )
                expected_no = move_no + 1
                if game.result is None:
                    winner = rules.other(game.current)
                    game.result = f"{winner.name} thang (Chieu het)"
                    game.current_node.result = game.result
                    game.refresh_current_snapshot()
                break

            match = _MOVE_PATTERN.match(line)
            if not match:
                if truncate_on_illegal:
                    metadata["truncated_illegal_move"] = raw_move
                    metadata["illegal_move_no"] = expected_no
                    break
                raise IllegalRecordMoveError(
                    f"Cú pháp nước đi không hợp lệ tại nước {expected_no}: {raw_move}",
                    move_no=expected_no,
                    move_text=raw_move,
                    game=game,
                    metadata=metadata,
                    applied_moves=len(list(game.nodes())) - 1,
                )

            (
                move_no_text,
                resign_tag,
                is_team_open,
                pcode,
                is_drop,
                dst_sq,
                dir_sym,
                dot_src,
                paren_src,
            ) = match.groups()
            move_no = int(move_no_text)

            if move_no != expected_no:
                # If move number skips slightly in loose txt, accommodate if sequential
                expected_no = move_no + 1
            else:
                expected_no += 1

            if resign_tag:
                game.resign()
                break

            dst_pos = last_dst_pos if dst_sq == "=" else sq_to_pos(dst_sq)
            if dst_pos is None:
                if truncate_on_illegal:
                    metadata["truncated_illegal_move"] = line
                    metadata["illegal_move_no"] = move_no
                    break
                raise IllegalRecordMoveError(
                    f"Ô đích không hợp lệ tại nước {move_no}: {dst_sq}",
                    move_no=move_no,
                    move_text=line,
                    game=game,
                    metadata=metadata,
                    applied_moves=len(list(game.nodes())) - 1,
                )
            last_dst_pos = dst_pos
            is_team = bool(is_team_open)
            src_pos = sq_to_pos(paren_src) if paren_src else (sq_to_pos(dot_src) if dot_src else None)

            current_player = game.current
            target_facing = DIR_MAP.get(dir_sym) if dir_sym else initial_facing(current_player)

            matching_moves: List[Move] = []
            candidate_moves = (
                _pseudo_legacy_compatible_moves(game)
                if allow_legacy_turnabout
                else rules.generate_moves(game.board, game.current)
            )
            for lm in candidate_moves:
                if is_drop and lm.kind != "drop":
                    continue
                if not is_drop and (
                    (is_team and lm.kind != "team")
                    or (not is_team and lm.kind not in ("single", "rotate"))
                ):
                    continue
                if (lm.kind != "rotate" and lm.dst != dst_pos) or (lm.kind == "rotate" and lm.src != dst_pos):
                    continue
                if src_pos and lm.src != src_pos:
                    continue

                if is_drop:
                    if PIECE_CODE.get(lm.ptype) != pcode.upper():
                        continue
                else:
                    sq_src = game.board.sq(*lm.src)
                    if sq_src.is_empty or PIECE_CODE.get(sq_src.top.ptype) != pcode.upper():
                        continue

                if lm.ptype not in NON_ROTATABLE:
                    if lm.kind == "drop":
                        if lm.facing != target_facing:
                            continue
                    elif not dir_sym:
                        if lm.rotate_after % 4 != 0:
                            continue
                    else:
                        sq_src = game.board.sq(*lm.src)
                        init_f = sq_src.top.facing if not sq_src.is_empty else 0
                        if (init_f + lm.rotate_after) % 4 != target_facing:
                            continue

                matching_moves.append(lm)

            matching_moves = [
                lm for lm in matching_moves
                if _record_candidate_is_legal(game, lm)
            ]

            matched_move = resolve_record_move_candidates(
                matching_moves,
                src_pos=src_pos,
                dst_pos=dst_pos,
            )
            if matched_move is None:
                if matching_moves:
                    err_msg = (
                        f"Nước đi không rõ ràng tại nước {move_no}: {line}; "
                        "cần thêm ô nguồn để phân biệt"
                    )
                else:
                    err_msg = f"Nước đi không hợp lệ (illegal move) tại nước {move_no}: {line}"

                if truncate_on_illegal:
                    metadata["truncated_illegal_move"] = line
                    metadata["illegal_move_no"] = move_no
                    break
                raise IllegalRecordMoveError(
                    err_msg,
                    move_no=move_no,
                    move_text=line,
                    game=game,
                    metadata=metadata,
                    applied_moves=len(list(game.nodes())) - 1,
                )

            raw_notation = line.split(".", 1)[1].strip() if "." in line else line
            clean_notation = strip_source_square(raw_notation)
            bypass = (
                allow_legacy_turnabout
                and matched_move.kind != "drop"
                and matched_move.rotate_after % 4 == 2
            )
            if not _commit_loaded_move(game, matched_move, clean_notation, bypass_validate=bypass):
                if truncate_on_illegal:
                    metadata["truncated_illegal_move"] = line
                    metadata["illegal_move_no"] = move_no
                    break
                raise IllegalRecordMoveError(
                    f"Không thể thực hiện nước đi tại nước {move_no}: {line}",
                    move_no=move_no,
                    move_text=line,
                    game=game,
                    metadata=metadata,
                    applied_moves=len(list(game.nodes())) - 1,
                )

        # Checkmate or terminal detection at end of mainline
        if game.result is None:
            status = rules.game_status(game.board, game.current)
            if status == "checkmate":
                game.result = f"{rules.other(game.current).name} thang (Chieu het)"
            elif status == "stalemate":
                game.result = f"{rules.other(game.current).name} thang (Doi thu bi PAT)"
            if game.result is not None:
                game.current_node.result = game.result
                game.refresh_current_snapshot()

        mainline_end = game.current_node

        # Apply variations if any
        if branches:
            def _n_ply(n):
                p = 0
                c = n
                while c.parent is not None:
                    p += 1
                    c = c.parent
                return p

            all_main_nodes = list(game.nodes())
            for br_ply, br_lines in branches:
                parent_candidates = [n for n in all_main_nodes if _n_ply(n) == br_ply - 1]
                if not parent_candidates:
                    continue
                branch_parent = parent_candidates[0]
                game.go_to_node(branch_parent)

                # Parse and apply branch moves
                br_text = "\n".join(br_lines)
                br_tokens = re.findall(
                    r"\d+(?:[\.\s]\s*|\s+)(?:Resign|Xin\s*thua|Xin\s*hàng|Xin\s*hang|#|"
                    r"(?:\[[VTSKXLBP]\]|[VTSKXLBP])\*?(?:[a-i][1-9]|=)[>^<˅˄vV]?(?:\.[a-i][1-9])?(?:\([a-i][1-9]\))?)",
                    br_text,
                    re.IGNORECASE,
                )
                for b_str in br_tokens:
                    b_str = b_str.strip()
                    if not b_str:
                        continue
                    m_b = _MOVE_PATTERN.match(b_str)
                    if not m_b:
                        continue
                    (
                        m_no_str,
                        r_tag,
                        t_open,
                        p_c,
                        drp,
                        d_sq,
                        d_sym,
                        dt_s,
                        prn_s,
                    ) = m_b.groups()
                    if r_tag:
                        game.resign()
                        break
                    d_pos = sq_to_pos(d_sq) if d_sq != "=" else last_dst_pos
                    if not d_pos:
                        continue
                    s_pos = sq_to_pos(prn_s) if prn_s else (sq_to_pos(dt_s) if dt_s else None)
                    t_facing = DIR_MAP.get(d_sym) if d_sym else initial_facing(game.current)

                    cand = rules.generate_moves(game.board, game.current)
                    m_moves = []
                    for lm in cand:
                        if bool(drp) and lm.kind != "drop":
                            continue
                        if not bool(drp) and lm.kind == "drop":
                            continue
                        if (lm.kind != "rotate" and lm.dst != d_pos) or (lm.kind == "rotate" and lm.src != d_pos):
                            continue
                        if s_pos and lm.src != s_pos:
                            continue
                        if bool(drp):
                            if PIECE_CODE.get(lm.ptype) != p_c.upper():
                                continue
                        else:
                            sq_src = game.board.sq(*lm.src)
                            if sq_src.is_empty or PIECE_CODE.get(sq_src.top.ptype) != p_c.upper():
                                continue
                        if lm.ptype not in NON_ROTATABLE:
                            if lm.kind == "drop":
                                if lm.facing != t_facing:
                                    continue
                            elif not d_sym:
                                if lm.rotate_after % 4 != 0:
                                    continue
                            else:
                                sq_src = game.board.sq(*lm.src)
                                init_f = sq_src.top.facing if not sq_src.is_empty else 0
                                if (init_f + lm.rotate_after) % 4 != t_facing:
                                    continue
                        m_moves.append(lm)

                    m_moves = [lm for lm in m_moves if _record_candidate_is_legal(game, lm)]
                    ch = resolve_record_move_candidates(m_moves, src_pos=s_pos, dst_pos=d_pos)
                    if ch:
                        b_raw = b_str.split(".", 1)[1].strip() if "." in b_str else b_str
                        b_clean = strip_source_square(b_raw)
                        _commit_loaded_move(game, ch, b_clean)

            # Return view to mainline end
            game.go_to_node(mainline_end)

        return metadata

    @staticmethod
    def load_lpgf(content: str, game: Game, *, truncate_on_illegal: bool = False) -> Dict[str, Any]:
        """Parse LPGF (v1.1 or v2.0), including optional custom-root ASCII diagram and variations."""
        mainline_text, branches = _extract_branch_blocks(content)
        numbered_moves: List[str] = []
        for raw_line in mainline_text.splitlines():
            line = raw_line.strip()
            if re.match(r"^\d+[\.\s]", line):
                numbered_moves.append(line)

        return LPGFNotation._apply_numbered_moves(
            content,
            game,
            numbered_moves,
            allow_legacy_turnabout=LPGFNotation._has_legacy_compat_marker(content),
            base_position=LPGFNotation._extract_base_position(content),
            allow_hash_mate=True,
            branches=branches,
            truncate_on_illegal=truncate_on_illegal,
        )

    @staticmethod
    def _legacy_txt_moves(content: str) -> List[str]:
        first = re.search(r"(?<!\S)1\.", content)
        if not first:
            first = re.search(r"(?<!\d)1\.", content)
        if not first:
            raise ValueError("TXT record does not contain move 1.")

        pos = first.start()
        move_no = 1
        moves: List[str] = []
        n = len(content)

        while pos < n:
            while pos < n and content[pos].isspace():
                pos += 1
            if pos >= n:
                break

            marker = f"{move_no}."
            if not content.startswith(marker, pos):
                next_pos = content.find(marker, pos)
                if next_pos < 0:
                    break
                if content[pos:next_pos].strip():
                    raise ValueError(
                        f"Unexpected text before move {move_no}: {content[pos:next_pos]!r}"
                    )
                pos = next_pos

            pos += len(marker)
            while pos < n and content[pos].isspace():
                pos += 1

            body_match = _TXT_MOVE_BODY_PATTERN.match(content, pos)
            if not body_match:
                preview = content[pos:pos + 40].replace("\n", " ").strip()
                first_word = preview.split()[0] if preview else "unknown"
                moves.append(f"{move_no}.{first_word}")
                break

            body = body_match.group(0)
            moves.append(f"{move_no}.{body}")
            pos = body_match.end()
            move_no += 1

        return moves

    @staticmethod
    def load_txt(content: str, game: Game, *, truncate_on_illegal: bool = False) -> Dict[str, Any]:
        """Parse historical compact TXT records and modern TXT with ASCII diagram and variations."""
        mainline_text, branches = _extract_branch_blocks(content)
        moves = LPGFNotation._legacy_txt_moves(mainline_text)
        return LPGFNotation._apply_numbered_moves(
            content,
            game,
            moves,
            allow_legacy_turnabout=True,
            base_position=LPGFNotation._extract_base_position(content),
            legacy_txt_semantics=True,
            allow_hash_mate=True,
            branches=branches,
            truncate_on_illegal=truncate_on_illegal,
        )

    @staticmethod
    def detect_format(content: str, filename: str = "") -> str:
        normalized = content.lstrip("\ufeff \t\r\n")
        if normalized.lower().startswith("#lpgf"):
            return "lpgf"
        if any(line.strip().startswith(POSITION_PREFIX) for line in content.splitlines()):
            return "lpgf"

        if re.search(r"(?im)^\s*Kỳ\s+Phổ\s+Game\s+Đấu\s*$", content):
            return "txt"
        if any(len(re.findall(r"(?<!\d)\d+\.", line)) > 1 for line in content.splitlines()):
            return "txt"

        ext = os.path.splitext(filename)[1].lower()
        if ext == ".lpgf":
            return "lpgf"
        if ext == ".txt":
            return "txt"

        if any(re.match(r"^\s*\d+[\.\s]", line) for line in content.splitlines()):
            return "lpgf"
        raise ValueError("Unable to detect record format from file content")

    @staticmethod
    def load_record(content: str, game: Game, filename: str = "", *, truncate_on_illegal: bool = False) -> Dict[str, Any]:
        fmt = LPGFNotation.detect_format(content, filename)
        if fmt == "txt":
            return LPGFNotation.load_txt(content, game, truncate_on_illegal=truncate_on_illegal)
        return LPGFNotation.load_lpgf(content, game, truncate_on_illegal=truncate_on_illegal)
