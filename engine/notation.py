

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
HEADER_KEYS = {
    "Tên Phòng:": "room_name",
    "Ngày Giờ Chơi:": "date",
    "Ngày Giờ Lưu:": "date",
    "Kỳ Thủ Thắng:": "winner",
    "Kỳ Thủ Cầm Cam:": "player_cam",
    "Kỳ Thủ Cầm Xanh:": "player_xanh",
}

POSITION_PREFIX = "#position "
COMPAT_LEGACY_TURNABOUT = "legacy-turnabout=1"

# One normalized numbered move, used by both modern LPGF and legacy TXT.
_MOVE_PATTERN = re.compile(
    r"^\s*(\d+)\.\s*(?:(Resign|Xin\s*thua|Xin\s*hàng|Xin\s*hang)|"
    r"(?:(\[?)([VTSKXLBP])\]?(\*?)([a-i][1-9]|=)([>^<˅˄vV]?)(?:\.([a-i][1-9]))?))\s*$",
    re.IGNORECASE,
)

# Legacy TXT move bodies are scanned independently from move numbers.  This is
# important because historical files may glue moves together, e.g.
# ``14.[K]i3<.g115.Ta5``.  A simple ``find("15.")`` is unsafe because board
# coordinates themselves also contain digits.
_TXT_MOVE_BODY_PATTERN = re.compile(
    r"(?:(?:Resign|Xin\s*thua|Xin\s*hàng|Xin\s*hang)|#|"
    r"(?:\[[VTSKXLBP]\]|[VTSKXLBP])\*?(?:[a-i][1-9]|=)"
    r"[>^<˅˄vV]?(?:\.[a-i][1-9])?)",
    re.IGNORECASE,
)


def pos_to_sq(pos: Tuple[int, int]) -> str:
    """Converts a (row, col) matrix index to board notation (e.g., (0, 8) -> 'a1')."""
    return f"{ROWS[pos[0]]}{COLS[pos[1]]}"


def sq_to_pos(sq_str: str) -> Optional[Tuple[int, int]]:
    """Converts board notation (e.g., 'a1') to a (row, col) matrix index."""
    if len(sq_str) < 2 or sq_str[0].lower() not in ROWS or sq_str[1] not in COLS:
        return None
    return ROWS.index(sq_str[0].lower()), COLS.index(sq_str[1])


def _legacy_compatible_moves(game: Game) -> List[Move]:
    """Return legal moves plus compatibility-only 180° rotations for old records.

    Live play still forbids 180° board rotations. This compatibility path exists
    only while loading historical records produced by older application builds.
    """
    base_moves = list(game.legal_moves())
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


def _record_candidate_is_legal(game: Game, move: Move) -> bool:
    """Validate one already notation-matched pseudo move.

    Record parsing used to call ``game.legal_moves()`` for the entire position,
    then call ``game.make_move()`` which generated the same huge legal list a
    second time.  Filtering the notation token first usually leaves only one or
    two candidates, so only those candidates need the expensive king-safety
    check.
    """
    try:
        b2 = game.board.clone()
        rules.apply_move(b2, game.current, move)
        return not rules.is_in_check(b2, game.current)
    except (ValueError, IndexError):
        return False


def _commit_loaded_move(game: Game, move: Move, notation_text: str, *, bypass_validate: bool = False) -> bool:
    """Apply an imported move that has already been resolved/validated.

    Terminal scanning is intentionally deferred while loading a record.  LPGF
    has explicit ``#``/resign markers, and repetition is still tracked on every
    move by ``commit_prevalidated_move``.  This removes one full legal-move
    generation per imported ply.
    """
    # ``bypass_validate`` remains part of the API for legacy 180-degree records;
    # ``rules.apply_move`` accepts those compatibility moves and the Game helper
    # does not regenerate live legal moves.
    return game.commit_prevalidated_move(
        move,
        notation_text=notation_text,
        check_terminal=False,
    )


def _base_position_payload(board: Board, current: Player) -> Dict[str, Any]:
    """Convert an arbitrary root position to a compact JSON-safe payload."""
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
    """Restore a root position previously emitted by _base_position_payload."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid #position payload")

    try:
        current = Player[payload["current"]]
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid player in #position payload") from exc

    board = Board()  # starts with an empty 9x9 grid
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
    """Resolve a notation token to one move using Co Long Phuong disambiguation rules.

    If a source square is written, that source is authoritative.

    If the source is omitted and an in-place rotation on the destination square
    matches the token, prefer that rotation.  This is the historical TXT
    convention: ``Bd8<`` may mean the Binh already on d8 rotates in place.

    A move arriving from another square must include ``.source`` whenever more
    than one interpretation exists.  Therefore a token such as ``Bd8<`` must not
    silently steal a Binh from c8 when a Binh on d8 can rotate to the requested
    facing.
    """
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

    # Without an explicit source, an arriving move is valid only when there is
    # one unique source/interpretation.
    sources = {mv.src for mv in unique}
    if len(sources) == 1 and len(unique) == 1:
        return unique[0]

    return None


class LPGFNotation:
    """Handles serialization and parsing of .lpgf and historical .txt record files."""

    @staticmethod
    def export_lpgf(
        game: Game,
        player_cam: str = "",
        player_xanh: str = "",
        save_time: Optional[datetime] = None,
    ) -> str:
        """Serialize the current branch, including optional custom-root metadata."""
        if any(len(n.children)>1 or n.comment or n.glyphs or n.metadata for n in game.nodes()) or game.current_node.children:
            raise ValueError('Legacy LPGF cannot preserve this tree/annotations. Use File -> Export LPGF (2.0).')
        save_time = save_time or datetime.now()
        name_cam = (player_cam or "").strip()
        name_xanh = (player_xanh or "").strip()
        display_cam = name_cam or "Cam"
        display_xanh = name_xanh or "Xanh"

        winner_str = "Chưa kết thúc"
        if game.result:
            res_lower = game.result.lower()
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
                winner_str = game.result

        path: List[MoveNode] = []
        curr = game.current_node
        while curr and curr.parent is not None:
            path.append(curr)
            curr = curr.parent
        path.reverse()

        has_custom_root = game.has_custom_base_position()
        needs_legacy_compat = any(
            node.move
            and node.move.kind != "drop"
            and node.move.rotate_after % 4 == 2
            for node in path
        )
        version = "1.1" if (has_custom_root or needs_legacy_compat) else "1.0"

        lines = [f"#lpgf version={version} encoding=UTF-8"]
        if has_custom_root:
            base_board, base_current = game.get_base_position()
            payload = _base_position_payload(base_board, base_current)
            lines.append(POSITION_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        if needs_legacy_compat:
            lines.append(f"#compat {COMPAT_LEGACY_TURNABOUT}")

        lines.extend([
            f"Ngày Giờ Lưu: {save_time.strftime('%d-%m-%Y %H:%M')}",
            f"Kỳ Thủ Thắng: {winner_str}",
            f"Kỳ Thủ Cầm Cam: {display_cam}",
            f"Kỳ Thủ Cầm Xanh: {display_xanh}",
            "",
        ])

        # Replay directly on a base-board copy. This works for both normal and
        # compatibility-only historical moves and avoids live-rule validation.
        sim_board, sim_current = game.get_base_position()
        for idx, node in enumerate(path, 1):
            if not node.move:
                continue
            notation_text = node.notation_text or node.move.notation(sim_board)
            lines.append(f"{idx}.{notation_text}")
            rules.apply_move(sim_board, sim_current, node.move)
            sim_current = rules.other(sim_current)

        if game.result:
            result_lower = game.result.lower()
            if "chieu het" in result_lower or "checkmate" in result_lower:
                # LPGF terminal marker: not a ply, but explicitly records mate.
                lines.append(f"{len(path) + 1}.#")
            elif any(k in result_lower for k in ("xin thua", "xin hang", "resign")):
                lines.append(f"{len(path) + 1}.Xin thua")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _metadata(content: str) -> Dict[str, Any]:
        metadata = {
            "version": "1.0",
            "room_name": "",
            "date": "",
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
                    metadata[key] = line_str.split(":", 1)[1].strip()
                    break
        return metadata

    @staticmethod
    def _extract_base_position(content: str) -> Optional[Tuple[Board, Player]]:
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
    ) -> Dict[str, Any]:
        """Apply already separated numbered move strings to ``game``."""
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
                    raise ValueError(f"Invalid record move: {raw_move}")
                if move_no != expected_no:
                    raise ValueError(f"Expected move {expected_no}, found move {move_no}: {line}")
                expected_no += 1

                # TXT uses a standalone numbered '#' marker after the mating move.
                # LPGF keeps its own result representation and never enters here.
                if game.result is None:
                    winner = rules.other(game.current)
                    game.result = f"{winner.name} thang (Chieu het)"
                    game.current_node.result = game.result
                    game.refresh_current_snapshot()
                break

            match = _MOVE_PATTERN.match(line)
            if not match:
                raise ValueError(f"Invalid record move: {raw_move}")

            (
                move_no_text,
                resign_tag,
                is_team_open,
                pcode,
                is_drop,
                dst_sq,
                dir_sym,
                src_sq,
            ) = match.groups()
            move_no = int(move_no_text)

            if move_no != expected_no:
                raise ValueError(f"Expected move {expected_no}, found move {move_no}: {line}")
            expected_no += 1

            if resign_tag:
                game.resign()
                break

            dst_pos = last_dst_pos if dst_sq == "=" else sq_to_pos(dst_sq)
            if dst_pos is None:
                raise ValueError(f"Invalid destination at move {move_no}: {dst_sq}")
            last_dst_pos = dst_pos
            is_team = bool(is_team_open)
            src_pos = sq_to_pos(src_sq) if src_sq else None

            current_player = game.current

            # TXT convention:
            #   - no direction symbol on a board move means "do not rotate";
            #   - ^ > v < specify the absolute final facing;
            #   - a drop without a symbol uses the owner's initial facing.
            # LPGF keeps the older absolute-facing interpretation for backwards
            # compatibility with already exported LPGF files.
            target_facing = DIR_MAP.get(dir_sym) if dir_sym else initial_facing(current_player)

            matching_moves: List[Move] = []
            # Normal LPGF/TXT parsing first filters cheap pseudo-legal moves by
            # the notation token, then king-safety-checks only the tiny matching
            # subset.  Legacy 180-degree files retain the compatibility path.
            candidate_moves = (
                _legacy_compatible_moves(game)
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
                    elif legacy_txt_semantics and not dir_sym:
                        # Standard TXT: omitted symbol means the moved piece keeps
                        # its current facing.  It does NOT reset to the owner's
                        # initial direction.
                        if lm.rotate_after % 4 != 0:
                            continue
                    else:
                        sq_src = game.board.sq(*lm.src)
                        init_f = sq_src.top.facing if not sq_src.is_empty else 0
                        if (init_f + lm.rotate_after) % 4 != target_facing:
                            continue

                matching_moves.append(lm)

            if not allow_legacy_turnabout:
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
                    raise ValueError(
                        f"Ambiguous record move {move_no}: {line}; "
                        "an arriving move needs an explicit .source square"
                    )
                raise ValueError(f"Illegal record move {move_no}: {line}")

            notation_text = line.split(".", 1)[1].strip() if "." in line else line
            bypass = (
                allow_legacy_turnabout
                and matched_move.kind != "drop"
                and matched_move.rotate_after % 4 == 2
            )
            if not _commit_loaded_move(game, matched_move, notation_text, bypass_validate=bypass):
                raise ValueError(f"Failed to apply record move {move_no}: {line}")

        # A configured maximum-ply draw is represented in the existing winner header.
        if game.result is None and metadata.get("winner") == "Draw (maximum plies reached)":
            game.result = metadata["winner"]
            game.refresh_current_snapshot()

        # Old records may omit an explicit checkmate marker.  One terminal scan
        # at the final position preserves that compatibility without paying for
        # a full legal-move generation after every imported ply.
        if game.result is None:
            status = rules.game_status(game.board, game.current)
            if status == "checkmate":
                game.result = f"{rules.other(game.current).name} thang (Chieu het)"
            elif status == "stalemate":
                game.result = f"{rules.other(game.current).name} thang (Doi thu bi PAT)"
            if game.result is not None:
                game.current_node.result = game.result
                game.refresh_current_snapshot()

        return metadata

    @staticmethod
    def load_lpgf(content: str, game: Game) -> Dict[str, Any]:
        """Parse LPGF, including optional custom-root and compatibility headers."""
        numbered_moves: List[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if re.match(r"^\d+\.", line):
                numbered_moves.append(line)

        return LPGFNotation._apply_numbered_moves(
            content,
            game,
            numbered_moves,
            allow_legacy_turnabout=LPGFNotation._has_legacy_compat_marker(content),
            base_position=LPGFNotation._extract_base_position(content),
            allow_hash_mate=True,
        )

    @staticmethod
    def _legacy_txt_moves(content: str) -> List[str]:
        """Tokenize compact TXT records without confusing square digits with move numbers.

        Historical files may place several moves on one line and may even glue
        consecutive moves together.  Parsing the move body first is reliable
        because destinations/source squares have a fixed two-character shape.
        """
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
                # Anything after the final parsed move is treated as footer text.
                # Inside the move section, however, unexpected non-whitespace is
                # a real syntax error rather than something to guess around.
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
                preview = content[pos:pos + 40].replace("\n", " ")
                raise ValueError(f"Invalid TXT move {move_no}: {preview}")

            body = body_match.group(0)
            moves.append(f"{move_no}.{body}")
            pos = body_match.end()
            move_no += 1

        return moves

    @staticmethod
    def load_txt(content: str, game: Game) -> Dict[str, Any]:
        """Parse historical compact TXT records produced by older versions."""
        return LPGFNotation._apply_numbered_moves(
            content,
            game,
            LPGFNotation._legacy_txt_moves(content),
            allow_legacy_turnabout=True,
            legacy_txt_semantics=True,
            allow_hash_mate=True,
        )

    @staticmethod
    def detect_format(content: str, filename: str = "") -> str:
        """Detect record syntax from content first, using extension only as fallback."""
        normalized = content.lstrip("\ufeff \t\r\n")
        if normalized.lower().startswith("#lpgf"):
            return "lpgf"
        if any(line.strip().startswith(POSITION_PREFIX) for line in content.splitlines()):
            return "lpgf"

        # Historical records identify themselves this way and often contain
        # multiple/glued move numbers on one physical line.
        if re.search(r"(?im)^\s*Kỳ\s+Phổ\s+Game\s+Đấu\s*$", content):
            return "txt"
        if any(len(re.findall(r"(?<!\d)\d+\.", line)) > 1 for line in content.splitlines()):
            return "txt"

        ext = os.path.splitext(filename)[1].lower()
        if ext == ".lpgf":
            return "lpgf"
        if ext == ".txt":
            return "txt"

        # Plain modern records without a header are accepted if numbered moves
        # are already one-per-line; this is the least surprising fallback.
        if any(re.match(r"^\s*\d+\.", line) for line in content.splitlines()):
            return "lpgf"
        raise ValueError("Unable to detect record format from file content")

    @staticmethod
    def load_record(content: str, game: Game, filename: str = "") -> Dict[str, Any]:
        """Auto-select the parser from content first, extension second."""
        fmt = LPGFNotation.detect_format(content, filename)
        if fmt == "txt":
            return LPGFNotation.load_txt(content, game)
        return LPGFNotation.load_lpgf(content, game)