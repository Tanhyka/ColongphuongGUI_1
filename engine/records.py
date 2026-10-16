"""Transactional record IO, preserving existing supported metadata and raw records."""
import json,re,uuid,hashlib
from .game import Game
from .notation import LPGFNotation,HEADER_KEYS
from .session import encode_game,atomic_write

def history_signature(game):
    data=encode_game(game);data.pop('selected',None)
    return json.dumps(data,ensure_ascii=False,sort_keys=True)

def load_record(content,filename=''):
    if not content.strip():raise ValueError('The record is empty.')
    if not (re.search(r'(?im)^\s*(#lpgf\b|#position\s|\d+\.)',content) or 'Kỳ Phổ Game Đấu' in content):
        raise ValueError('No LPGF header, position or numbered moves were found.')
    if re.match(r'^\s*#lpgf\s+2\.0\s*\n',content):
        from .tree_record import load_tree
        game,meta=load_tree(content.lstrip())
    else:
        if re.search(r'(?im)^#lpgf\s+(?:version=)?(?!1\.[01]\b)\d+\.\d+',content):raise ValueError('Unsupported LPGF version')
        game=Game();meta=LPGFNotation.load_record(content,game,filename)
        # Stable, repeatable legacy identity without altering the original record.
        game.game_id=hashlib.sha256(content.encode('utf8')).hexdigest()
        for i,node in enumerate(game.nodes()):node.node_id=uuid.uuid5(uuid.NAMESPACE_URL,game.game_id+':'+str(i)).hex
        if '#compat legacy-turnabout=1' in content or any(n.move and n.move.rotate_after==2 for n in game.nodes()):meta['legacy_turnabout']=True
    meta.update(original_text=content,original_format=LPGFNotation.detect_format(content,filename),signature=history_signature(game))
    return game,meta

def export_record(game,metadata=None,player_cam='Cam',player_xanh='Xanh'):
    meta=metadata or {};original=meta.get('original_text');unchanged=meta.get('signature')==history_signature(game)
    if original and unchanged and meta.get('original_format')=='lpgf' and not original.lstrip().startswith('#lpgf 2.0'):
        text=original
        for key,value in [('Kỳ Thủ Cầm Cam:',player_cam),('Kỳ Thủ Cầm Xanh:',player_xanh)]:
            if re.search('(?m)^'+re.escape(key),text):text=re.sub('(?m)^'+re.escape(key)+r'[^\r\n]*',lambda m:key+' '+value,text)
        return text
    from .tree_record import export_tree
    metadata=dict(meta,player_cam=player_cam,player_xanh=player_xanh)
    if original and not original.lstrip().startswith('#lpgf 2.0'):
        metadata['legacy_source_text']=original
    return export_tree(game,metadata)


def write_record(path,game,metadata=None,**names):
    content=export_record(game,metadata,**names)
    atomic_write(path,content)
    return content
