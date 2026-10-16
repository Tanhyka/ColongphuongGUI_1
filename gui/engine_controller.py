"""Async generic CLP-EP controller; bundled Python state/history, no Legacy CLI."""
from engine.client import Client
from engine import registry
class EngineController(Client):
    def __init__(self,parent=None,engine_path=None):
        super().__init__(parent)
        if engine_path:self.set_engine_path(engine_path)
    def start_search(self,game,move_time_ms=1500,clocks=None):
        if not self.engine_path:
            entry=next((e for e in registry.load() if registry.playable(e)),None)
            if not entry:self.errorOccurred.emit('No playable engine registered. Add a CLP-EP v1 executable in Engine Settings.');return False
            self.set_engine_path(entry['path'],entry.get('args',[]),entry.get('options',{}))
        from engine.protocol import export_game
        try:
            return super().start_search(export_game(game),move_time_ms,clocks)
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            self.errorOccurred.emit(str(exc))
            return False
