"""CLP-EP v1 adapter using the application's existing Python rules only.

No DLL dependency, no alternate move generator, no replacement of full history
with a single position. Protocol schemas follow Ryuugin docs/CLP_EP_V1.md.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib,json,time
from .board import Board
from .pieces import Piece,PieceType,Player
from .game import Game,_position_hash,_same_move
from .rules import Move
from . import rules
from .lppn import _validate_board


def position(board,side):
    _validate_board(board,True)
    return dict(board=[[dict(type=p.ptype.name,owner=p.owner.name,facing=p.facing) for p in board.sq(r,c).stack] for r in range(9) for c in range(9)],to_move=side.name,
                reserve={p.name:[v.name for v in board.reserve[p]] for p in Player},prisoners={p.name:[v.name for v in board.prisoners[p]] for p in Player})

def board_from_position(value):
    if not isinstance(value,dict) or set(value)!={'board','to_move','reserve','prisoners'}:raise ValueError('Invalid CLP position fields')
    if not isinstance(value['board'],list) or len(value['board'])!=81:raise ValueError('Expected 81 squares')
    b=Board();side=Player[value['to_move']]
    for i,stack in enumerate(value['board']):
        if not isinstance(stack,list):raise ValueError('Invalid stack')
        for p in stack:
            if not isinstance(p,dict) or set(p)!={'type','owner','facing'}:raise ValueError('Invalid piece fields')
            b.sq(i//9,i%9).stack.append(Piece(PieceType[p['type']],Player[p['owner']],p['facing']))
    for field in ('reserve','prisoners'):
        hand=value[field]
        if not isinstance(hand,dict) or set(hand)!={'CAM','XANH'}:raise ValueError('Invalid hands')
        if any(not isinstance(v,list) for v in hand.values()):raise ValueError('Invalid hand array')
        setattr(b,field,{p:[PieceType[v] for v in hand[p.name]] for p in Player})
    _validate_board(b,True)
    return b,side

def result_wire(game):
    if game.result is None:return {'status':'ongoing'}
    text=game.result.lower();side=game.current
    if 'maximum plies' in text:return dict(status='terminal',reason='max_plies',winner=None,loser=None)
    if '3 lan' in text:reason='repetition3';winner=side
    elif 'chieu het' in text:reason='checkmate';winner=rules.other(side)
    elif 'pat' in text:reason='pat';winner=rules.other(side)
    elif 'xin thua' in text:reason='resign';winner=rules.other(side)
    else:raise ValueError('This game result has no verified CLP-EP v1 mapping; analyze an ongoing position instead.')
    return dict(status='terminal',reason=reason,winner=winner.name,loser=rules.other(winner).name)

def export_game(game):
    nodes=[];node=game.current_node
    while node is not None:nodes.append(node);node=node.parent
    nodes.reverse();entries={};counts=Counter()
    for node in nodes:
        b=node._snapshot_board;s=node._snapshot_current
        if b is None or s is None:raise ValueError('Complete history snapshot unavailable')
        key=_position_hash(b,s);counts[key]+=1
        entries[key]={'position':position(b,s),'count':counts[key]}
    if counts!=game.pos_counts or _position_hash(game.board,game.current)!=_position_hash(game.current_node._snapshot_board,game.current_node._snapshot_current):
        raise ValueError('History/position mismatch; refusing to invent repetition history')
    if len(entries)>4096:raise ValueError('CLP history exceeds 4096 distinct positions; not truncated')
    state=dict(schema='clp.state/1',position=position(game.board,game.current),ply=len(nodes)-1,repetition=dict(complete=True,entries=list(entries.values())),result=result_wire(game),notation=None)
    validate_state(state)
    if len(json.dumps(state,ensure_ascii=False,separators=(',',':')).encode())>1048576:raise ValueError('CLP payload too large; history not truncated')
    return state

def position_id(state):return hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def validate_state(state):
    if not isinstance(state,dict) or set(state)!={'schema','position','ply','repetition','result','notation'} or state['schema']!='clp.state/1':raise ValueError('Invalid state schema')
    if type(state['ply'])!=int or not 0<=state['ply']<=1000000:raise ValueError('Invalid ply')
    board,side=board_from_position(state['position']);rep=state['repetition']
    if not isinstance(rep,dict) or set(rep)!={'complete','entries'} or rep['complete'] is not True or not isinstance(rep['entries'],list) or not 1<=len(rep['entries'])<=4096:raise ValueError('Full repetition history required')
    counts=Counter()
    for entry in rep['entries']:
        if not isinstance(entry,dict) or set(entry)!={'position','count'} or type(entry['count'])!=int or not 1<=entry['count']<=3:raise ValueError('Invalid history entry')
        b,s=board_from_position(entry['position']);key=_position_hash(b,s)
        if key in counts:raise ValueError('Duplicate repetition identity')
        counts[key]=entry['count']
    if _position_hash(board,side) not in counts:raise ValueError('Current position missing from history')
    result=state['result']
    if result=={'status':'ongoing'}:
        if max(counts.values())>=3 or rules.game_status(board,side)!='ongoing':raise ValueError('False ongoing state')
    else:
        if not isinstance(result,dict) or set(result)!={'status','reason','winner','loser'} or result['status']!='terminal' or result['reason'] not in ('max_plies','resign','repetition3','checkmate','pat'):raise ValueError('Invalid terminal state')
        if result['reason']=='max_plies':
            if result['winner'] is not None or result['loser'] is not None:raise ValueError('Invalid maximum-ply result')
        elif result['winner'] not in ('CAM','XANH') or result['loser']!=rules.other(Player[result['winner']]).name:raise ValueError('Invalid result sides')
        if result['reason']=='repetition3' and (counts[_position_hash(board,side)]!=3 or result['winner']!=side.name):raise ValueError('False repetition result')
        if result['reason'] in ('checkmate','pat') and (rules.game_status(board,side)!=('checkmate' if result['reason']=='checkmate' else 'stalemate') or result['loser']!=side.name):raise ValueError('False terminal claim')
    notation=state['notation']
    if notation is not None:
        if not isinstance(notation,dict) or set(notation)!={'format','text','legacy_turnabout'} or notation['format'] not in ('LPGF','TXT') or not isinstance(notation['text'],str) or len(notation['text'].encode('utf8'))>8192 or type(notation['legacy_turnabout'])!=bool:raise ValueError('Invalid archival notation context')
    return state

def move_from_wire(value):
    fields={'schema','kind','src','dst','ptype','facing','rotate_after','notation'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!='clp.move/1':raise ValueError('Invalid move schema')
    if value['notation'] is not None and (not isinstance(value['notation'],str) or len(value['notation'].encode())>8192):raise ValueError('Invalid notation')
    def square(v):
        if v is None:return None
        if not isinstance(v,list) or len(v)!=2 or any(type(n)!=int or not 0<=n<9 for n in v):raise ValueError('Invalid square')
        return tuple(v)
    if type(value['rotate_after'])!=int or value['rotate_after'] not in (0,1,3):raise ValueError('Invalid rotation')
    if value['facing'] is not None and (type(value['facing'])!=int or value['facing'] not in range(4)):raise ValueError('Invalid facing')
    return Move(value['kind'],square(value['src']),square(value['dst']),PieceType[value['ptype']],value['facing'],value['rotate_after'])

def simulation(state):
    b,s=board_from_position(state['position']);g=Game();g.set_base_position(b,s)
    g.pos_counts=Counter({_position_hash(*board_from_position(e['position'])):e['count'] for e in state['repetition']['entries']})
    if state['result']['status']=='terminal':g.result='terminal'
    return g

def apply_wire(game,value):
    move=move_from_wire(value)
    candidate=next((m for m in game.legal_moves() if _same_move(m,move)),None)
    if candidate is None:raise ValueError('Engine supplied illegal move/PV')
    text=candidate.notation(game.board)
    if not game.commit_prevalidated_move(candidate,check_terminal=True):raise ValueError('Move after terminal state')
    return candidate,text

def validate_info(state,value,request_id,requested):
    fields={'schema','id','depth','nodes','time_ms','multipv','score','bound','pv'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!='clp.info/1' or value['id']!=request_id:raise ValueError('Invalid correlated info schema')
    for name,lo,hi in [('id',1,2147483647),('depth',0,1024),('nodes',0,2**53-1),('time_ms',0,86400000),('multipv',1,requested)]:
        if type(value[name])!=int or not lo<=value[name]<=hi:raise ValueError('Invalid info '+name)
    score=value['score']
    if not isinstance(score,dict) or set(score)!={'kind','value','perspective'} or score['perspective']!='root' or type(score['value'])!=int:raise ValueError('Invalid score semantics')
    if score['kind'] not in ('cp','mate','value_milli') or abs(score['value'])>(1000 if score['kind']=='value_milli' else 1000000 if score['kind']=='mate' else 2**53-1):raise ValueError('Invalid score')
    if score['kind']=='mate' and score['value']==0 and not (state['result'].get('reason')=='checkmate'):raise ValueError('Mate zero requires checkmated terminal root')
    if value['bound'] not in ('exact','lower','upper') or not isinstance(value['pv'],list) or len(value['pv'])>256:raise ValueError('Invalid PV/bound')
    g=simulation(state);notations=[];deadline=time.monotonic()+1.0
    for move in value['pv']:
        if time.monotonic()>deadline:raise ValueError('PV validation budget exceeded')
        _,text=apply_wire(g,move);notations.append(text)
    return {'info':value,'notations':notations}

@dataclass
class EngineInfo:
    depth:int|None=None
    nodes:int|None=None
    time_ms:int|None=None
    score:int|None=None
    score_kind:str|None=None
    pv:list|None=None
    multipv:int=1
    engine_id:str=''
    session_id:tuple|None=None
    position_id:str=''
    score_perspective:str='unknown'
    root_side:str|None=None
    nps:int|None=None
    seldepth:int|None=None
    wdl:tuple|None=None
    neural_value:int|None=None
    hybrid_value:int|None=None
    confidence:int|None=None
    bestmove:Move|None=None
    bound:str='exact'
