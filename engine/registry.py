"""Atomic settings-backed registrations. Metadata is learned by async probe."""
import json,os
from pathlib import Path
from PyQt6.QtCore import QSettings
ORG_NAME='ColongphuongGUI';APP_NAME='ColongphuongGUI'
def settings():
    path=os.environ.get('CLP_SETTINGS_FILE')
    if not path:
        from .session import data_dir
        directory=data_dir();directory.mkdir(parents=True,exist_ok=True)
        path=str(directory/'preferences.ini')
    s=QSettings(path,QSettings.Format.IniFormat)
    if not os.environ.get('CLP_SETTINGS_FILE') and not s.allKeys():
        legacy=QSettings(ORG_NAME,APP_NAME)
        for key in legacy.allKeys():s.setValue(key,legacy.value(key))
        s.sync()
    s.setAtomicSyncRequired(True);return s
def load():
    raw=settings().value('engines/list','[]')
    try:entries=json.loads(raw) if isinstance(raw,str) else []
    except (ValueError,TypeError):entries=[]
    return [dict(e) for e in entries if isinstance(e,dict)]
def playable(entry):
    caps=entry.get('capabilities',{})
    return entry.get('protocol')=='clp-ep/1' and caps.get('search')==['legal'] and caps.get('position')==['rules'] and Path(entry.get('path','')).is_file()
def save(entries):
    if not isinstance(entries,list):raise ValueError('Registry list required')
    s=settings();s.setValue('engines/list',json.dumps(entries,ensure_ascii=False));s.sync()
    if s.status()!=QSettings.Status.NoError:raise OSError('Engine registry atomic sync failed')
def register(metadata,path,args=None,options=None,old=None):
    path=str(Path(path).resolve());args=list(args or [])
    if not Path(path).is_file() or any(not isinstance(a,str) or len(a)>1024 or '\x00' in a for a in args):raise ValueError('Invalid executable/arguments')
    if metadata.get('protocol')!='clp-ep/1' or not all(isinstance(metadata.get(k),str) and metadata[k] for k in ('name','author','version','kind')):raise ValueError('Verified CLP metadata required')
    values=dict(options or {})
    for name,value in values.items():
        definition=metadata.get('options',{}).get(name)
        if not definition or type(value)!=int or not definition['min']<=value<=definition['max']:raise ValueError('Invalid engine option '+name)
    entry={**metadata,'path':path,'args':args,'option_definitions':metadata.get('options',{}),'options':values}
    entries=load();match=next((i for i,e in enumerate(entries) if os.path.normcase(e.get('path',''))==os.path.normcase(path) and e.get('args',[])==args),None)
    if old is not None:
        index=next((i for i,e in enumerate(entries) if (e.get('id')==old.get('id') if old.get('id') else e==old)),None)
        if index is not None:
            if match is not None and match!=index:raise ValueError('Duplicate executable and arguments')
            match=index
    import uuid
    entry['id']=entries[match].get('id',str(uuid.uuid4())) if match is not None else str(uuid.uuid4())
    # Name collisions are display labels only; preserve true handshake name separately.
    entry['engine_name']=metadata['name'];entry['name']=metadata['name']
    if any(i!=match and e.get('name')==entry['name'] for i,e in enumerate(entries)):entry['name']=f"{metadata['name']} [{entry['id'][:8]}]"
    if match is None:entries.append(entry)
    else:entries[match]=entry
    save(entries);return entry
def remove(entry_id):save([e for e in load() if e.get('id')!=entry_id]) # registration only
