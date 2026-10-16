"""Provisional LPGF 2.0: ordered, parented nodes; rule-replayed on import.

No cached boards or repetition maps are trusted from record files.
"""
import json
import re
from .game import Game, _same_move
from .notation import _base_position_payload, _board_from_base_payload, _legacy_compatible_moves
from .pieces import PieceType
from .rules import Move

GLYPHS = ('!', '?', '!!', '??', '!?', '?!')
HEADER = '#lpgf 2.0\n'


def strict_json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('Duplicate JSON key: ' + k)
            result[k] = v
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Invalid number')))
    except RecursionError as exc:
        raise ValueError('JSON nesting exceeds supported limit') from exc


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise ValueError('Invalid stable identity')
    return value


def node_annotations(entry):
    if not isinstance(entry.get('comment', ''), str) or len(entry.get('comment', '')) > 100000:
        raise ValueError('Invalid node comment')
    glyphs = entry.get('glyphs', [])
    if not isinstance(glyphs, list) or len(glyphs) > 6 or len(set(glyphs)) != len(glyphs) or any(g not in GLYPHS for g in glyphs):
        raise ValueError('Invalid annotation glyph')
    if not isinstance(entry.get('metadata', {}), dict):
        raise ValueError('Invalid node metadata')


def move_data(move):
    if move is None:
        return None
    return dict(kind=move.kind, src=move.src, dst=move.dst,
                ptype=move.ptype.name if move.ptype else None,
                facing=move.facing, rotate_after=move.rotate_after)


def parse_move(data):
    if not isinstance(data, dict) or set(data) != {'kind','src','dst','ptype','facing','rotate_after'}:
        raise ValueError('Invalid move fields')
    m = dict(data)
    if m['kind'] not in ('single','team','drop','rotate'):
        raise ValueError('Invalid move kind')
    for k in ('src','dst'):
        if m[k] is not None:
            if not isinstance(m[k], list) or len(m[k]) != 2 or any(type(v) != int or not 0 <= v < 9 for v in m[k]):
                raise ValueError('Invalid move square')
            m[k] = tuple(m[k])
    if type(m['rotate_after']) != int or m['rotate_after'] not in (0,1,2,3):
        raise ValueError('Invalid move rotation')
    if m['facing'] is not None and (type(m['facing']) != int or m['facing'] not in range(4)):
        raise ValueError('Invalid move facing')
    m['ptype'] = PieceType[m['ptype']] if m['ptype'] else None
    return Move(**m)


def tree_payload(game, metadata=None):
    entries = []
    for n in game.nodes():
        node_annotations(dict(comment=n.comment, glyphs=n.glyphs, metadata=n.metadata))
        entries.append(dict(id=n.node_id, parent=n.parent.node_id if n.parent else None,
                            move=move_data(n.move), notation=n.notation_text, comment=n.comment,
                            glyphs=n.glyphs, metadata=n.metadata, result=n.result))
    meta = {k:v for k,v in (metadata or {}).items() if k not in ('original_text','signature','original_format')}
    return dict(schema='lpgf.tree/2.0-provisional', game_id=game.game_id,
                root=_base_position_payload(game.base_board, game.base_current),
                base_ply=game.base_ply, max_plies=game.max_plies,
                selected=game.current_node.node_id, nodes=entries,
                metadata=meta, extensions=game.metadata)


def export_tree(game, metadata=None):
    return HEADER + json.dumps(tree_payload(game, metadata), ensure_ascii=False, sort_keys=True, indent=2) + '\n'


def load_tree(content):
    if len(content.encode('utf8')) > 32*1024*1024:
        raise ValueError('LPGF exceeds 32 MiB')
    data = strict_json(content.split('\n',1)[1])
    if not isinstance(data, dict) or data.get('schema') != 'lpgf.tree/2.0-provisional':
        raise ValueError('Unsupported LPGF tree schema')
    required = {'schema','game_id','root','base_ply','max_plies','selected','nodes','metadata','extensions'}
    if set(data) != required:
        raise ValueError('Unknown structural fields: preserve them inside metadata/extensions')
    entries = data['nodes']
    if not isinstance(entries,list) or not 1 <= len(entries) <= 20000:
        raise ValueError('Invalid node count')
    board, side = _board_from_base_payload(data['root'])
    if _base_position_payload(board,side) != data['root']:
        raise ValueError('Invalid root position')
    from .lppn import _validate_board
    _validate_board(board,False)
    game = Game();game.set_base_position(board,side)
    game.game_id = identity(data['game_id'])
    if type(data['base_ply']) != int or not 0 <= data['base_ply'] <= 1000000:
        raise ValueError('Invalid base ply')
    game.base_ply = data['base_ply'];game.max_plies = data['max_plies']
    if game.max_plies is not None and (type(game.max_plies) != int or game.max_plies < 1):
        raise ValueError('Invalid maximum plies')
    if not isinstance(data['metadata'],dict) or not isinstance(data['extensions'],dict):
        raise ValueError('Invalid metadata')
    game.metadata = data['extensions'];nodes = {}
    legacy = data['metadata'].get('legacy_turnabout') is True
    for i, e in enumerate(entries):
        if not isinstance(e,dict) or set(e) != {'id','parent','move','notation','comment','glyphs','metadata','result'}:
            raise ValueError('Invalid node fields')
        key = identity(e['id'])
        if key in nodes:raise ValueError('Duplicate node ID')
        node_annotations(e)
        if not isinstance(e['notation'],str) or len(e['notation']) > 8192 or (e['result'] is not None and not isinstance(e['result'],str)):
            raise ValueError('Invalid notation/result')
        if i == 0:
            if e['parent'] is not None or e['move'] is not None:raise ValueError('Invalid root node')
            node = game.root
        else:
            parent = nodes.get(e['parent'])
            if parent is None:raise ValueError('Missing/forward branch parent')
            game.go_to_node(parent)
            move = parse_move(e['move'])
            candidates = _legacy_compatible_moves(game) if legacy else game.legal_moves()
            candidate = next((m for m in candidates if _same_move(m,move)),None)
            if candidate is None:raise ValueError('Illegal branch move or move after terminal')
            if any(_same_move(c.move,move) for c in parent.children):raise ValueError('Duplicate sibling move')
            if not game.commit_prevalidated_move(candidate,notation_text=e['notation'],check_terminal=True):raise ValueError('Cannot apply move')
            node = game.current_node
        # Preserve archival terminal text. Rules-derived results must agree.
        if game.result is not None and e['result'] != game.result:
            raise ValueError('Contradictory terminal result')
        node.node_id = key;node.notation_text = e['notation'];node.comment = e['comment']
        node.glyphs = e['glyphs'];node.metadata = e['metadata']
        game.result = e['result'];game.refresh_current_snapshot();nodes[key] = node
    selected = nodes.get(data['selected'])
    if selected is None:raise ValueError('Missing selected node')
    game.go_to_node(selected)
    return game, data['metadata']
