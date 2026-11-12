"""Atomic settings-backed registrations. Metadata is learned by async probe."""
import json, os
from pathlib import Path
from PyQt6.QtCore import QSettings

ORG_NAME = 'ColongphuongGUI'
APP_NAME = 'ColongphuongGUI'

def settings():
    path = os.environ.get('CLP_SETTINGS_FILE')
    if not path:
        from .session import data_dir
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = str(directory / 'preferences.ini')
    s = QSettings(path, QSettings.Format.IniFormat)
    if not os.environ.get('CLP_SETTINGS_FILE') and not s.allKeys():
        legacy = QSettings(ORG_NAME, APP_NAME)
        for key in legacy.allKeys():
            s.setValue(key, legacy.value(key))
        s.sync()
    s.setAtomicSyncRequired(True)
    return s

def _find_homei_candidates():
    candidates = []
    base_dirs = [
        Path(r"E:\code5\Homei\HomeiEngine\build\Engine realese"),
        Path(r"E:\code5\Homei\HomeiEngine\build\Engine release"),
        Path(r"D:\code5\Homei\HomeiEngine\build\Engine realese"),
        Path(r"D:\code5\Homei\HomeiEngine\build\Engine release"),
    ]
    for d in base_dirs:
        if d.is_dir():
            for p in sorted(d.glob("*.exe"), reverse=True):
                if p.is_file():
                    candidates.append(p)
    for bf in [
        Path(r"E:\code5\Homei\HomeiEngine\build\homei.exe"),
        Path(r"D:\code5\Homei\HomeiEngine\build\homei.exe"),
    ]:
        if bf.is_file() and bf not in candidates:
            candidates.append(bf)
    json_path = Path(r"E:\code5\ColongphuongGUI_train\engines.json")
    if json_path.is_file():
        try:
            cfg = json.loads(json_path.read_text(encoding='utf-8'))
            exe = Path(cfg.get('executable', ''))
            if exe.is_file() and exe not in candidates:
                candidates.append(exe)
        except Exception:
            pass
    return candidates

def load():
    raw = settings().value('engines/list', '[]')
    try:
        entries = json.loads(raw) if isinstance(raw, str) else []
    except (ValueError, TypeError):
        entries = []
    result = [dict(e) for e in entries if isinstance(e, dict)]
    modified = False

    # Auto-normalize generic "Homei" names if executable has specific version stem
    for e in result:
        p = e.get('path', '')
        if p == 'builtin://clp_core_cli' and e.get('name') in ('CLP C++ Engine', 'CLP C++ Engine V1'):
            e['name'] = 'CLP C++ Engine V1 (Heuristic)'
            e['engine_name'] = 'CLP C++ Engine V1 (Heuristic)'
            modified = True
        elif p and p != 'builtin://clp_core_cli':
            p_obj = Path(p)
            stem = p_obj.stem
            cur_name = e.get('name', '')
            if stem and (cur_name == 'Homei' or cur_name.startswith('Homei [') or not cur_name) and stem.lower() != 'homei':
                e['name'] = stem
                e['engine_name'] = stem
                modified = True
            if (not e.get('author') or e.get('author') == 'Unknown') and 'homei' in stem.lower():
                e['author'] = 'Homei Team'
                modified = True

    # Auto-discover Homei if not in list
    registered_paths = {os.path.normcase(e.get('path', '')) for e in result if Path(e.get('path', '')).is_file()}
    for h in _find_homei_candidates():
        if os.path.normcase(str(h)) not in registered_paths:
            stem_name = h.stem
            homei_entry = {
                'id': f"homei-{h.stem.lower()}",
                'name': stem_name,
                'engine_name': stem_name,
                'author': 'Homei Team',
                'version': '1.0',
                'kind': 'CLP-EP v1',
                'path': str(h.resolve()),
                'args': [],
                'protocol': 'clp-ep/1',
                'capabilities': {'search': ['legal', 'infinite'], 'clocks': ['movetime'], 'control': ['stop']},
                'options': {'Depth': 12, 'Nodes': 50000000, 'MultiPV': 1},
                'option_definitions': {
                    'Depth': {'type': 'spin', 'default': 12, 'min': 1, 'max': 32},
                    'Nodes': {'type': 'spin', 'default': 50000000, 'min': 1, 'max': 50000000},
                    'MultiPV': {'type': 'spin', 'default': 1, 'min': 1, 'max': 5}
                }
            }
            result.insert(0, homei_entry)
            registered_paths.add(os.path.normcase(str(h)))
            modified = True
            break

    if modified:
        try:
            save(result)
        except Exception:
            pass
    return result

def playable(entry):
    if not isinstance(entry, dict):
        return False
    p = entry.get('path', '')
    if p == 'builtin://clp_core_cli':
        return True
    if not p or not Path(p).is_file():
        return False
    caps = entry.get('capabilities', {})
    search_caps = caps.get('search', [])
    return entry.get('protocol') in ('clp-ep/1', 'clp-ep 1') and ('legal' in search_caps or not search_caps)

def save(entries):
    if not isinstance(entries, list):
        raise ValueError('Registry list required')
    s = settings()
    s.setValue('engines/list', json.dumps(entries, ensure_ascii=False))
    s.sync()
    if s.status() != QSettings.Status.NoError:
        raise OSError('Engine registry atomic sync failed')

def register(metadata, path, args=None, options=None, old=None):
    path = str(Path(path).resolve())
    args = list(args or [])
    if not Path(path).is_file() or any(not isinstance(a, str) or len(a) > 1024 or '\x00' in a for a in args):
        raise ValueError('Invalid executable/arguments')
    metadata = dict(metadata or {})
    metadata.setdefault('protocol', 'clp-ep/1')
    metadata.setdefault('author', 'Homei Team')
    metadata.setdefault('version', '1.0')
    metadata.setdefault('kind', 'CLP-EP v1')

    # Priority: explicit name/engine_name in metadata -> executable stem -> handshake name
    chosen_name = metadata.get('name') or metadata.get('engine_name') or Path(path).stem
    if chosen_name.lower() == 'homei' and path != 'builtin://clp_core_cli':
        stem = Path(path).stem
        if stem and stem.lower() != 'homei':
            chosen_name = stem
    metadata['name'] = chosen_name
    metadata['engine_name'] = chosen_name

    if metadata.get('protocol') not in ('clp-ep/1', 'clp-ep 1') or not all(isinstance(metadata.get(k), str) and metadata[k] for k in ('name', 'author', 'version', 'kind')):
        raise ValueError('Verified CLP metadata required')
    values = dict(options or {})
    for name, value in values.items():
        definition = metadata.get('options', {}).get(name)
        if not definition or type(value) != int or not definition['min'] <= value <= definition['max']:
            raise ValueError('Invalid engine option ' + name)
    entry = {**metadata, 'name': chosen_name, 'engine_name': chosen_name, 'path': path, 'args': args, 'option_definitions': metadata.get('options', {}), 'options': values}
    entries = load()
    match = next((i for i, e in enumerate(entries) if os.path.normcase(e.get('path', '')) == os.path.normcase(path) and e.get('args', []) == args), None)
    if old is not None:
        index = next((i for i, e in enumerate(entries) if (e.get('id') == old.get('id') if old.get('id') else e == old)), None)
        if index is not None:
            if match is not None and match != index:
                raise ValueError('Duplicate executable and arguments')
            match = index
    import uuid
    entry['id'] = entries[match].get('id', str(uuid.uuid4())) if match is not None else str(uuid.uuid4())
    entry['engine_name'] = chosen_name
    entry['name'] = chosen_name
    if any(i != match and e.get('name') == entry['name'] for i, e in enumerate(entries)):
        entry['name'] = f"{chosen_name} [{entry['id'][:8]}]"
    if match is None:
        entries.append(entry)
    else:
        entries[match] = entry
    save(entries)
    return entry

def remove(entry_id):
    save([e for e in load() if e.get('id') != entry_id])
