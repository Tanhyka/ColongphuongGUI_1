"""Versioned session storage. Never writes user record files."""
from __future__ import annotations
import hashlib,json,os,uuid
from collections import Counter
from pathlib import Path
from .game import Game,MoveNode
from .rules import Move
from .pieces import PieceType
from .notation import _base_position_payload, _board_from_base_payload

SCHEMA=1

def data_dir():
    return Path(os.environ.get('CLP_DATA_DIR') or Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'ColongphuongGUI_1')

def atomic_write(path, text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf8',newline='\n') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)

def encode_game(game):
    nodes=[]; queue=[game.root]; index={id(game.root):0}
    for node in queue:
        for child in node.children:
            index[id(child)]=len(queue);queue.append(child)
        board=node._snapshot_board
        if board is None:raise ValueError('History snapshot missing')
        move=None
        if node.move:
            m=node.move;move=dict(kind=m.kind,src=m.src,dst=m.dst,ptype=m.ptype.name if m.ptype else None,facing=m.facing,rotate_after=m.rotate_after)
        nodes.append(dict(node_id=node.node_id,glyphs=node.glyphs,metadata=node.metadata,parent=index[id(node.parent)] if node.parent else None,move=move,notation=node.notation_text,comment=node.comment,result=node.result,position=_base_position_payload(board,node._snapshot_current),snapshot_result=node._snapshot_result,counts=dict(node._snapshot_pos_counts)))
    return dict(nodes=nodes,selected=index[id(game.current_node)],base_ply=getattr(game,'base_ply',0),max_plies=game.max_plies,extensions=game.metadata,game_id=game.game_id)

def decode_game(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('nodes'),list) or not 1<=len(payload['nodes'])<=20000:raise ValueError('Invalid history')
    game=Game();nodes=[];ids=set()
    for i,entry in enumerate(payload['nodes']):
        board,side=_board_from_base_payload(entry['position'])
        # Check payload roundtrip: reject silently coerced facing/coordinates/missing fields.
        if _base_position_payload(board,side)!=entry['position']:raise ValueError('Invalid position data')
        parent=entry['parent']
        if i==0:
            if parent is not None or entry['move'] is not None:raise ValueError('Invalid root')
            game.set_base_position(board,side);node=game.root
        else:
            if type(parent)!=int or not 0<=parent<i:raise ValueError('Invalid parent')
            m=dict(entry['move']);m['ptype']=PieceType[m['ptype']] if m['ptype'] else None
            for key in ('src','dst'):
                if m[key] is not None:
                    if len(m[key])!=2 or any(type(c)!=int or not 0<=c<9 for c in m[key]):raise ValueError('Invalid move square')
                    m[key]=tuple(m[key])
            if m['kind'] not in ('single','team','rotate','drop'):raise ValueError('Invalid move kind')
            node=MoveNode(Move(**m),nodes[parent]);nodes[parent].children.append(node)
        from .tree_record import identity,node_annotations
        node.node_id=identity(entry.get('node_id',node.node_id))
        if node.node_id in ids:raise ValueError('Duplicate node ID')
        ids.add(node.node_id);node_annotations(entry)
        node.glyphs=entry.get('glyphs',[]);node.metadata=entry.get('metadata',{})
        node.notation_text=entry['notation'];node.comment=entry['comment'];node.result=entry['result']
        counts=entry['counts']
        if not isinstance(counts,dict) or any(type(v)!=int or v<1 for v in counts.values()):raise ValueError('Invalid repetition counts')
        node._snapshot_board=board;node._snapshot_current=side;node._snapshot_result=entry['snapshot_result'];node._snapshot_pos_counts=Counter(counts);nodes.append(node)
    selected=payload['selected']
    if type(selected)!=int or not 0<=selected<len(nodes):raise ValueError('Invalid selected ply')
    game.game_id=identity(payload.get('game_id',game.game_id));game.metadata=payload.get('extensions',{})
    game.go_to_node(nodes[selected]);game.base_ply=payload.get('base_ply',0);game.max_plies=payload.get('max_plies')
    if type(game.base_ply)!=int or not 0<=game.base_ply<=1000000:raise ValueError('Invalid base ply')
    if game.max_plies is not None and (type(game.max_plies)!=int or game.max_plies<1):raise ValueError('Invalid maximum plies')
    return game

class SessionStore:
    def __init__(self,path=None):
        self.directory=Path(path) if path else data_dir();self.errors=[]
    def _read(self,name):
        path=self.directory/name
        if not path.exists():return None
        try:
            if path.stat().st_size>64*1024*1024:raise ValueError('Snapshot too large')
            envelope=json.loads(path.read_text(encoding='utf8'));data=envelope['payload']
            raw=json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':'))
            if hashlib.sha256(raw.encode()).hexdigest()!=envelope['sha256']:raise ValueError('Checksum mismatch')
            if data['schema']!=SCHEMA:raise ValueError('Unsupported session schema')
            if type(data.get('clean'))!=bool:raise ValueError('Invalid clean marker')
            decode_game(data['game'])
            if 'workspace' not in data or not isinstance(data['workspace'],dict):raise ValueError('Invalid workspace')
            ws=data['workspace']
            if ws.get('training_review') is not None:
                from .review import validate_workspace
                validate_workspace(ws['training_review'])
            for key in ('flipped','dirty','moves_enabled'):
                if key in ws and type(ws[key])!=bool:raise ValueError('Invalid workspace flag')
            if ws.get('source') is not None and not isinstance(ws['source'],str):raise ValueError('Invalid source path')
            if 'setup' in ws and not isinstance(ws['setup'],dict):raise ValueError('Invalid setup')
            if ws.get('editor'):
                draft=ws['editor'];board,side=_board_from_base_payload(draft['position'])
                if _base_position_payload(board,side)!=draft['position']:raise ValueError('Invalid editor draft')
                if draft.get('tool') not in ('move','delete','place'):raise ValueError('Invalid editor tool')
            return data
        except (ValueError,KeyError,TypeError,IndexError,OSError,AttributeError,RecursionError) as exc:
            self.errors.append(f'{name}: {exc}');return None
    def _write(self,name,data):
        raw=json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        text=json.dumps(dict(sha256=hashlib.sha256(raw.encode()).hexdigest(),payload=data),ensure_ascii=False)
        if len(text.encode('utf8'))>64*1024*1024:raise ValueError('Snapshot exceeds 64 MiB; previous snapshot retained')
        atomic_write(self.directory/name,text)
    def save(self,game,workspace,*,clean=False):
        data=dict(schema=SCHEMA,clean=clean,game=encode_game(game),workspace=workspace,extensions={})
        # Validate before replacing either known-good file.
        decode_game(data['game'])
        previous=self._read('session.json')
        if previous:self._write('previous.json',previous)
        self._write('session.json',data)
    def interrupted(self):
        current=self._read('session.json') or self._read('previous.json')
        if current and not current['clean']:
            self._write('recoverable.json',current)
            return current
        return None
    def recoverable(self):
        return self._read('recoverable.json') or self._read('session.json') or self._read('previous.json')
