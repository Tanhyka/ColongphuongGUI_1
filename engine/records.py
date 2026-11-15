"""Transactional record IO, preserving existing supported metadata and raw records."""
import json
import re
import uuid
import hashlib
from .game import Game
from .notation import LPGFNotation, HEADER_KEYS, IllegalRecordMoveError
from .session import encode_game, atomic_write


def history_signature(game):
    data = encode_game(game)
    data.pop('selected', None)
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def load_record(content, filename='', *, truncate_on_illegal=False):
    if not content.strip():
        raise ValueError('The record is empty.')
    if not (re.search(r'(?im)^\s*(#lpgf\b|#position\s|\d+[\.\s])', content) or 'Kỳ Phổ Game Đấu' in content):
        raise ValueError('No LPGF header, position or numbered moves were found.')

    # Legacy provisional JSON tree format
    if re.match(r'^\s*#lpgf\s+2\.0\s*\{', content):
        from .tree_record import load_tree
        game, meta = load_tree(content.lstrip())
    else:
        game = Game()
        try:
            meta = LPGFNotation.load_record(content, game, filename, truncate_on_illegal=truncate_on_illegal)
        except IllegalRecordMoveError as exc:
            if exc.game is not None:
                exc.game.game_id = hashlib.sha256(content.encode('utf8')).hexdigest()
                for i, node in enumerate(exc.game.nodes()):
                    node.node_id = uuid.uuid5(uuid.NAMESPACE_URL, exc.game.game_id + ':' + str(i)).hex
                if '#compat legacy-turnabout=1' in content or any(n.move and n.move.rotate_after == 2 for n in exc.game.nodes()):
                    exc.metadata['legacy_turnabout'] = True
                exc.metadata.update(
                    original_text=content,
                    original_format=LPGFNotation.detect_format(content, filename),
                    signature=history_signature(exc.game),
                )
                exc.game._truncated_illegal = True
            raise exc

        # Stable, repeatable legacy identity without altering the original record.
        game.game_id = hashlib.sha256(content.encode('utf8')).hexdigest()
        for i, node in enumerate(game.nodes()):
            node.node_id = uuid.uuid5(uuid.NAMESPACE_URL, game.game_id + ':' + str(i)).hex
        if '#compat legacy-turnabout=1' in content or any(n.move and n.move.rotate_after == 2 for n in game.nodes()):
            meta['legacy_turnabout'] = True

    meta.update(
        original_text=content,
        original_format=LPGFNotation.detect_format(content, filename),
        signature=history_signature(game),
    )
    return game, meta


def export_record(game, metadata=None, player_cam=None, player_xanh=None, format_type=None):
    meta = metadata or {}
    cam = player_cam or meta.get('player_cam') or 'Cam'
    xanh = player_xanh or meta.get('player_xanh') or 'Xanh'
    fmt = (format_type or meta.get('target_format') or '').lower().strip().lstrip('.')

    # Explicit format requests (all LPGF exports now write 2.0; 1.1 is import-only)
    if fmt == 'txt':
        return LPGFNotation.export_txt(game, player_cam=cam, player_xanh=xanh, metadata=meta)

    return LPGFNotation.export_lpgf(game, player_cam=cam, player_xanh=xanh, metadata=meta, version="2.0")


def write_record(path, game, metadata=None, format_type=None, **names):
    if format_type is None:
        p = str(path).lower()
        if p.endswith('.txt'):
            format_type = 'txt'
        elif p.endswith('.lpgf'):
            format_type = 'lpgf20'
    content = export_record(game, metadata, format_type=format_type, **names)
    atomic_write(path, content)
    return content
