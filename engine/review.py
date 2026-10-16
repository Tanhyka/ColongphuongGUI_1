"""Versioned human observations, separate from game records and engine proof."""
import hashlib,json,uuid
from datetime import datetime,timezone
from pathlib import Path
from .game import _position_hash
from .session import atomic_write
from .tree_record import strict_json,identity

SCHEMA='clp.human-review/1'
REASONS=('Evaluation','Move choice','Tactics','King safety','Material','Rules','Mate claim','Other')


def position_identity(game):
    value=dict(position=_position_hash(game.board,game.current),counts=dict(game.pos_counts),result=game.result)
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode('utf8')).hexdigest()


def validate_values(value):
    if not isinstance(value,dict) or set(value)!={'judgement','reasons','confidence','notes','mate'}:
        raise ValueError('Invalid human review fields')
    if value['judgement'] not in ('ACCEPT','REJECT','UNKNOWN'):raise ValueError('Invalid judgement')
    reasons=value['reasons']
    if not isinstance(reasons,list) or any(r not in REASONS for r in reasons) or len(set(reasons))!=len(reasons):raise ValueError('Invalid review reasons')
    if type(value['confidence'])!=int or not 0<=value['confidence']<=100:raise ValueError('Invalid confidence')
    if not isinstance(value['notes'],str) or len(value['notes'])>100000:raise ValueError('Invalid notes')
    mate=value['mate']
    if not isinstance(mate,dict) or set(mate)!={'claim','attacker','candidate_line','defenses','verification','solver_status'}:raise ValueError('Invalid mate fields')
    if type(mate['claim'])!=bool or mate['attacker'] not in ('CAM','XANH'):raise ValueError('Invalid mate claim')
    if any(not isinstance(mate[k],str) or len(mate[k])>100000 for k in ('candidate_line','defenses')):raise ValueError('Invalid mate text')
    if mate['verification']!='UNVERIFIED' or mate['solver_status']!='PENDING_ENGINE_SUPPORT':raise ValueError('No complete mate solver is available; proof cannot be asserted')
    return value


def make_review(game,values,source=None):
    validate_values(values)
    record=dict(schema=SCHEMA,review_id=uuid.uuid4().hex,game_id=game.game_id,
                source_ref=source,node_id=game.current_node.node_id,position_id=position_identity(game),
                side=game.current.name,timestamp=datetime.now(timezone.utc).isoformat(),
                status='HUMAN_OBSERVATION',engine_recommendation=None,**values)
    return validate_review(record)


def validate_review(record):
    fields={'schema','review_id','game_id','source_ref','node_id','position_id','side','timestamp','status','engine_recommendation','judgement','reasons','confidence','notes','mate'}
    if not isinstance(record,dict) or set(record)!=fields or record['schema']!=SCHEMA:raise ValueError('Unsupported review schema/fields')
    for field in ('review_id','game_id','node_id'):identity(record[field])
    if not isinstance(record['position_id'],str) or len(record['position_id'])!=64 or any(c not in '0123456789abcdef' for c in record['position_id']):raise ValueError('Invalid position identifier')
    if record['source_ref'] is not None and (not isinstance(record['source_ref'],str) or len(record['source_ref'])>32768):raise ValueError('Invalid source reference')
    if record['side'] not in ('CAM','XANH') or record['status']!='HUMAN_OBSERVATION':raise ValueError('Invalid review status')
    if record['engine_recommendation'] is not None:raise ValueError('Engine recommendation import not supported in schema 1')
    if not isinstance(record['timestamp'],str):raise ValueError('Invalid timestamp')
    try:
        stamp=datetime.fromisoformat(record['timestamp'])
        if stamp.tzinfo is None:raise ValueError('Timestamp must include timezone')
    except (ValueError,TypeError) as exc:raise ValueError('Invalid review timestamp') from exc
    validate_values({k:record[k] for k in ('judgement','reasons','confidence','notes','mate')})
    return record


def validate_reviews(records):
    if not isinstance(records,list) or len(records)>20000:raise ValueError('Invalid review count')
    ids=set()
    for record in records:
        validate_review(record)
        if record['review_id'] in ids:raise ValueError('Duplicate review ID')
        ids.add(record['review_id'])
    return records


def load_reviews(text):
    if len(text.encode('utf8'))>32*1024*1024:raise ValueError('Review file exceeds 32 MiB')
    return validate_reviews([strict_json(line) for line in text.splitlines() if line.strip()])


def save_reviews(path,records):
    validate_reviews(records)
    target=Path(path).resolve()
    if target.suffix.lower()!='.jsonl':raise ValueError('Review data must use a separate .jsonl file')
    if target.is_relative_to(Path(__file__).resolve().parents[1]):raise ValueError('Keep review data outside application source')
    text=''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in records)
    if len(text.encode('utf8'))>32*1024*1024:raise ValueError('Review file exceeds 32 MiB')
    atomic_write(target,text)


def validate_workspace(value):
    if not isinstance(value,dict) or set(value)!={'schema','records','drafts','active','return_node','return_moves','return_layout'} or value['schema']!='clp.review-workspace/1':
        raise ValueError('Invalid review recovery schema')
    validate_reviews(value['records'])
    if not isinstance(value['drafts'],dict) or len(value['drafts'])>20000:raise ValueError('Invalid review drafts')
    for key,record in value['drafts'].items():
        validate_review(record)
        if key!=record['game_id']+':'+record['node_id']:raise ValueError('Draft identity mismatch')
    if type(value['active'])!=bool or type(value['return_moves'])!=bool:raise ValueError('Invalid review workspace flags')
    if value['return_node'] is not None:identity(value['return_node'])
    layout=value['return_layout']
    if layout is not None:
        import base64
        if not isinstance(layout,dict) or set(layout)!={'version','geometry','state','engine'} or layout['version']!=5:raise ValueError('Invalid return layout')
        for field in ('geometry','state','engine'):
            if not isinstance(layout[field],str) or len(layout[field])>1048576 or not base64.b64decode(layout[field],validate=True):raise ValueError('Invalid return layout encoding')
    return value
