"""Move generation & rules engine for Co Long Phuong."""

from dataclasses import dataclass
from typing import Optional, List, Tuple, Generator
from .board import Board, SIZE
from .pieces import Piece, PieceType, Player, initial_facing, NON_ROTATABLE, PIECE_CODE

ROW_DROP = {Player.CAM: 1, Player.XANH: 7}
# 40 quân tổng cộng, 2 Vương không bao giờ thuộc đội => tối đa 38 quân/đội.
MAX_STACK_SIZE = 38
ROWS = "abcdefghi"
COLS = "987654321"

DIR_SYMBOLS = {0: "˄", 1: ">", 2: "˅", 3: "<"}


def other(player: Player) -> Player:
    return Player.XANH if player is Player.CAM else Player.CAM


@dataclass
class Move:
    kind: str  # 'rotate' | 'single' | 'team' | 'drop'
    src: Optional[Tuple[int, int]] = None
    dst: Optional[Tuple[int, int]] = None
    ptype: Optional[PieceType] = None
    facing: Optional[int] = None
    rotate_after: int = 0

    def notation(self, board: Optional['Board'] = None) -> str:
        def sq(pos: Tuple[int, int]) -> str:
            return f"{ROWS[pos[0]]}{COLS[pos[1]]}"

        moving_piece = None
        ptype = self.ptype

        if board:
            # A drop's piece type comes from the move itself.  The destination
            # may already contain a friendly piece, but that piece must not
            # replace the dropped type in notation.
            if self.kind != 'drop' and self.src:
                square_src = board.sq(*self.src)
                if not square_src.is_empty:
                    moving_piece = square_src.top
                    ptype = moving_piece.ptype
                elif self.dst:
                    square_dst = board.sq(*self.dst)
                    if not square_dst.is_empty:
                        moving_piece = square_dst.top
                        ptype = moving_piece.ptype

        piece_code = PIECE_CODE.get(ptype, "") if ptype else ""
        if self.kind == 'team':
            piece_code = f"[{piece_code}]"

        drop_mark = "*" if self.kind == 'drop' else ""
        dst_pos = self.dst or self.src
        dst_str = sq(dst_pos) if dst_pos else ""

        dir_symbol = ""
        if ptype and ptype not in NON_ROTATABLE:
            curr_f = self.facing if self.kind == 'drop' else (moving_piece.facing if moving_piece else 0)
            final_f = (curr_f + self.rotate_after) % 4
            dir_symbol = DIR_SYMBOLS.get(final_f, "")

        src_str = ""
        if self.kind != 'drop' and board and self.src and moving_piece:
            if self.kind == 'rotate':
                # Rotation shares the same compact core notation as a piece
                # moving into this square. Always include the source square so
                # the parser can distinguish the two cases deterministically.
                src_str = f".{sq(self.src)}"
            elif self.dst:
                ambiguous_count = sum(
                    1
                    for r in range(SIZE)
                    for c in range(SIZE)
                    if not board.sq(r, c).is_empty
                    and board.sq(r, c).top.owner == moving_piece.owner
                    and board.sq(r, c).top.ptype == moving_piece.ptype
                    and any(dest == self.dst for dest, _ in _raw_destinations(board, r, c))
                )

                # A same-type friendly piece already on the destination may
                # also produce the same text by rotating in place. Treat that
                # as an ambiguity even when only one piece can move there.
                dest_sq = board.sq(*self.dst)
                rotate_conflict = (
                    not dest_sq.is_empty
                    and dest_sq.top.owner is moving_piece.owner
                    and dest_sq.top.ptype is moving_piece.ptype
                    and dest_sq.top.can_rotate()
                )
                if ambiguous_count > 1 or rotate_conflict:
                    src_str = f".{sq(self.src)}"

        if self.kind == 'rotate':
            return f"{piece_code}{dst_str}{dir_symbol}{src_str}"

        return f"{piece_code}{drop_mark}{dst_str}{dir_symbol}{src_str}"


def _raw_destinations(board: Board, r: int, c: int) -> Generator[Tuple[Tuple[int, int], str], None, None]:
    """Yields ((r2, c2), kind) where kind is 'empty' | 'capture' | 'own'."""
    sq = board.sq(r, c)
    if sq.is_empty:
        return

    piece = sq.top
    owner = piece.owner

    for kind, (dr, dc) in piece.moves():
        if kind in ('step', 'jump'):
            r2, c2 = r + dr, c + dc
            if not Board.in_bounds(r2, c2):
                continue
            dest = board.sq(r2, c2)
            if dest.is_empty:
                yield ((r2, c2), 'empty')
            elif dest.owner is owner:
                yield ((r2, c2), 'own')
            else:
                yield ((r2, c2), 'capture')
        elif kind == 'slide':
            r2, c2 = r + dr, c + dc
            while Board.in_bounds(r2, c2):
                dest = board.sq(r2, c2)
                if dest.is_empty:
                    yield ((r2, c2), 'empty')
                elif dest.owner is owner:
                    yield ((r2, c2), 'own')
                    break
                else:
                    yield ((r2, c2), 'capture')
                    break
                r2, c2 = r2 + dr, c2 + dc


def is_attacked(board: Board, r: int, c: int, by_player: Player) -> bool:
    return any(
        dest == (r, c)
        for rr in range(SIZE)
        for cc in range(SIZE)
        if not board.sq(rr, cc).is_empty and board.sq(rr, cc).top.owner is by_player
        for dest, _ in _raw_destinations(board, rr, cc)
    )


def is_in_check(board: Board, player: Player) -> bool:
    king_pos = board.find_king(player)
    return is_attacked(board, king_pos[0], king_pos[1], other(player)) if king_pos else False


def reserve_pending(board: Board, player: Player) -> List[PieceType]:
    return board.reserve[player]


def generate_moves(board: Board, player: Player) -> List[Move]:
    pending = reserve_pending(board, player)
    if pending:
        return [mv for ptype in set(pending) for mv in _reserve_drop_moves(board, player, ptype)]

    moves: List[Move] = _prisoner_drop_moves(board, player)

    for r in range(SIZE):
        for c in range(SIZE):
            square = board.sq(r, c)
            if square.is_empty or square.top.owner is not player:
                continue

            top = square.top
            is_stack = len(square.stack) > 1
            # Quân đang ở trên bàn chỉ được xoay trái/phải (90 độ).
            # Không được xoay 180 độ trong cùng một nước đi.
            rotate_options = [0, 1, 3] if top.can_rotate() else [0]

            for (r2, c2), kind in _raw_destinations(board, r, c):
                dest_square = board.sq(r2, c2)

                # Vương is never captured.  _raw_destinations must still expose
                # the square so is_attacked()/check detection can see attacks.
                if kind == 'capture' and any(p.ptype is PieceType.VUONG for p in dest_square.stack):
                    continue

                # Đi quân lẻ:
                # - vào ô trống / bắt quân đối phương: luôn có thể xét tiếp theo luật chiếu;
                # - chồng lên quân mình: chỉ khi quân nguồn đang đứng lẻ, không có Vương,
                #   và đội đích chưa đạt giới hạn 38 quân. Quân tách ra từ một đội
                #   không được tạo đội ngay trong cùng nước đi.
                can_single = kind != 'own'
                if kind == 'own':
                    can_single = (
                        not is_stack
                        and top.ptype is not PieceType.VUONG
                        and not any(p.ptype is PieceType.VUONG for p in dest_square.stack)
                        and len(dest_square.stack) < MAX_STACK_SIZE
                    )
                if can_single:
                    for rot in rotate_options:
                        moves.append(Move('single', (r, c), (r2, c2), ptype=top.ptype, rotate_after=rot))

                # Đi đội: cả chồng đi theo cách đi của quân trên cùng; không được
                # chồng lên quân mình và Vương không bao giờ thuộc/đi cùng đội.
                if (
                    is_stack
                    and kind != 'own'
                    and not any(p.ptype is PieceType.VUONG for p in square.stack)
                ):
                    for rot in rotate_options:
                        moves.append(Move('team', (r, c), (r2, c2), ptype=top.ptype, rotate_after=rot))

            # Xoay tại chỗ: chỉ cho phép xoay trái/phải 90 độ.
            if top.can_rotate():
                for rot in (1, 3):
                    moves.append(Move('rotate', src=(r, c), ptype=top.ptype, rotate_after=rot))

    return moves


def _reserve_drop_moves(board: Board, player: Player, ptype: PieceType) -> List[Move]:
    """Thả Long/Phượng từ hàng dự bị với đủ 4 hướng xoay."""
    row = ROW_DROP[player]
    facings = [0, 1, 2, 3] if ptype not in NON_ROTATABLE else [initial_facing(player)]
    out: List[Move] = []

    for c in range(SIZE):
        dest = board.sq(row, c)
        if dest.is_empty or (dest.owner == player and dest.top.ptype is not PieceType.VUONG and len(dest.stack) < MAX_STACK_SIZE):
            for f in facings:
                out.append(Move('drop', dst=(row, c), ptype=ptype, facing=f))
    return out


def _prisoner_drop_moves(board: Board, player: Player) -> List[Move]:
    """Thả tù binh ăn được từ tay lên bàn cờ với đủ 4 hướng xoay."""
    out: List[Move] = []
    base_f = initial_facing(player)

    for ptype in set(board.prisoners[player]):
        facings = [base_f] if ptype in NON_ROTATABLE else [0, 1, 2, 3]

        for r in range(SIZE):
            for c in range(SIZE):
                dest = board.sq(r, c)
                if not dest.is_empty and (dest.owner is not player or dest.top.ptype is PieceType.VUONG or len(dest.stack) >= MAX_STACK_SIZE):
                    continue
                for f in facings:
                    out.append(Move('drop', dst=(r, c), ptype=ptype, facing=f))

    return out


def legal_moves(board: Board, player: Player) -> List[Move]:
    out = []
    for mv in generate_moves(board, player):
        b2 = board.clone()
        apply_move(b2, player, mv)
        if not is_in_check(b2, player):
            out.append(mv)
    return out


def apply_move(board: Board, player: Player, move: Move) -> Optional[PieceType]:
    """Apply one already-selected move and defensively enforce the common rules.

    Game.make_move() normally filters through legal_moves() first, but history
    reconstruction and tests also call this function directly. Keeping the core
    stack/Vương rules here prevents an invalid state from being created silently.
    """
    captured = None

    if move.kind == 'drop':
        if move.dst is None or move.ptype is None:
            raise ValueError("Drop requires destination and piece type")
        dest = board.sq(*move.dst)
        if not dest.is_empty:
            if dest.owner is not player:
                raise ValueError("A dropped piece cannot be placed on an opponent-owned square")
            if any(p.ptype is PieceType.VUONG for p in dest.stack):
                raise ValueError("VUONG cannot be part of a stack")
            if len(dest.stack) >= MAX_STACK_SIZE:
                raise ValueError(f"A stack cannot exceed {MAX_STACK_SIZE} pieces")

        target_list = board.reserve[player] if move.ptype in board.reserve[player] else board.prisoners[player]
        if move.ptype not in target_list:
            raise ValueError("Dropped piece is not available in reserve/prisoners")
        dest.stack.append(Piece(move.ptype, player, (move.facing or 0) % 4))
        target_list.remove(move.ptype)
        return None

    if move.src is None:
        raise ValueError(f"{move.kind} requires a source square")

    src = board.sq(*move.src)
    if src.is_empty or src.owner is not player:
        raise ValueError("Source square does not contain the current player's piece")

    if move.kind == 'rotate':
        if not src.top.can_rotate():
            raise ValueError(f"{src.top.ptype.name} cannot rotate")
        src.top.facing = (src.top.facing + move.rotate_after) % 4
        return None

    if move.dst is None:
        raise ValueError(f"{move.kind} requires a destination square")
    dst = board.sq(*move.dst)

    if move.kind == 'single':
        source_was_stack = len(src.stack) > 1
        moving_piece = src.top

        # Chồng lên quân mình chỉ được phép với một quân đang đứng lẻ.
        if not dst.is_empty and dst.owner is player:
            if source_was_stack:
                raise ValueError("A piece split from a stack cannot create another stack in the same move")
            if moving_piece.ptype is PieceType.VUONG or any(p.ptype is PieceType.VUONG for p in dst.stack):
                raise ValueError("VUONG cannot be part of a stack")
            if len(dst.stack) >= MAX_STACK_SIZE:
                raise ValueError(f"A stack cannot exceed {MAX_STACK_SIZE} pieces")

        moving = [src.stack.pop()]

    elif move.kind == 'team':
        if len(src.stack) < 2:
            raise ValueError("Team move requires at least two stacked pieces")
        if any(p.ptype is PieceType.VUONG for p in src.stack):
            raise ValueError("VUONG cannot move as part of a team")
        if not dst.is_empty and dst.owner is player:
            raise ValueError("A team cannot stack onto another friendly piece/team")
        moving = src.stack[:]
        src.stack = []
    else:
        raise ValueError(move.kind)

    # Ăn quân đối phương. Vương chỉ có thể bị chiếu/chiếu hết, không bị bắt.
    if not dst.is_empty and dst.owner is not player:
        if any(p.ptype is PieceType.VUONG for p in dst.stack):
            raise ValueError("Cannot capture VUONG; the game must end by checkmate")
        for p in dst.stack:
            captured = p.ptype
            board.prisoners[player].append(p.ptype)
        dst.stack.clear()

    # Chỉ quân trên cùng / quân vừa di chuyển được xoay. Khi đi đội,
    # moving[-1] chính là quân trên cùng của đội.
    if move.rotate_after:
        if not moving[-1].can_rotate():
            raise ValueError(f"{moving[-1].ptype.name} cannot rotate")
        moving[-1].facing = (moving[-1].facing + move.rotate_after) % 4

    dst.stack.extend(moving)
    return captured


def game_status(board: Board, player_to_move: Player) -> str:
    if legal_moves(board, player_to_move):
        return 'ongoing'
    return 'checkmate' if is_in_check(board, player_to_move) else 'stalemate'