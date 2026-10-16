"""Optional CLP-EP validation DLL bridge (NOT required for GUI gameplay).

Gameplay and editing use Python rules bundled in engine/. A separate C++
service may validate external engine messages once CLP-EP is integrated.
"""

from __future__ import annotations

import ctypes
import json
import os
import threading
from pathlib import Path


class CoreUnavailable(RuntimeError):
    """The authoritative C++ rules DLL is not available."""


def _candidates():
    """Explicit override first; otherwise common project/library build locations."""
    configured = os.environ.get('CLP_CORE_LIBRARY', '').strip().strip('"')
    if configured:
        yield Path(configured).expanduser()
        return
    project = Path(__file__).resolve().parents[1]
    workspace = project.parent  # usually D:/Code
    roots = [
        project / 'bin', project / 'external',
        workspace / 'Library' / 'cpp-CLP',
        workspace / 'CLP_engine' / 'Ryuugin',
    ]
    children = ('', 'build', 'build/Release', 'build/Debug',
                'build/windows-release/Release', 'build/windows-debug/Debug',
                'build/step3')
    filenames = ('ryuugin_rules.dll', 'clp_rules_service.dll')
    for root in roots:
        for child in children:
            for filename in filenames:
                yield root / child / filename


class Core:
    """Authoritative C++ wrapper; throws on incompatible service or bad API."""

    def __init__(self, path):
        self.path = Path(path)
        self.library = ctypes.CDLL(str(self.path))
        self.function = self.library.clp_core_json
        self.function.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
        self.function.restype = ctypes.c_size_t
        self.buffer = ctypes.create_string_buffer(65536)
        self.lock = threading.RLock()
        self.metadata = self.call('metadata')
        if self.metadata.get('api') != 'ryuugin.rules/1':
            raise RuntimeError('DLL cung cấp API không tương thích (yêu cầu ryuugin.rules/1)')
        self.available = True
        self.problem = ''

    def call(self, command, **fields):
        wire = json.dumps({'command': command, **fields}, ensure_ascii=False,
                          separators=(',', ':')).encode('utf8')
        if len(wire) > 1048576:
            raise ValueError('Rules request exceeds CLP payload limit; history must not be truncated')
        with self.lock:
            needed = self.function(wire, self.buffer, len(self.buffer))
            if needed > 1048577 or needed == 0:
                raise ValueError('Invalid rule-service response size')
            if needed > len(self.buffer):
                self.buffer = ctypes.create_string_buffer(needed)
                if self.function(wire, self.buffer, len(self.buffer)) != needed:
                    raise ValueError('Unstable rule-service response')
            result = json.loads(self.buffer.value.decode('utf8'))
        if isinstance(result, dict) and 'error' in result:
            raise ValueError(result['error'])
        return result


class UnavailableCore:
    """Only describes missing optional C++ validator; never invents board state."""

    available = False
    path = None
    metadata = {'api': 'unavailable/1'}

    def __init__(self, reason):
        self.problem = reason

    def call(self, command, **fields):
        raise CoreUnavailable(
            f"Bộ xác minh CLP-EP C++ tùy chọn không có sẵn ({command}). "
            f"GUI vẫn sử dụng luật Python nội bộ. {self.problem}"
        )


_core = None
_lock = threading.Lock()


def core():
    global _core
    with _lock:
        if _core is None:
            tried = []
            for candidate in _candidates():
                if not candidate.is_file():
                    tried.append(str(candidate))
                    continue
                try:
                    _core = Core(candidate)
                    break
                except (OSError, AttributeError, RuntimeError, ValueError) as error:
                    tried.append(f'{candidate} — {type(error).__name__}: {error}')
            if _core is None:
                override = os.environ.get('CLP_CORE_LIBRARY')
                detail = ('CLP_CORE_LIBRARY=' + override if override else
                          'Không tìm thấy DLL tương thích trong project/Library/CLP_engine.')
                if tried and override:
                    detail += '\n' + tried[0]
                _core = UnavailableCore(detail)
    return _core
