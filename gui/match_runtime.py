"""Small runtime helpers for Step 3.3 match lifecycle.

Kept free of PyQt so it can be tested deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from engine.pieces import Player


@dataclass
class SideClock:
    main_ms: int
    period_ms: int
    period_remaining_ms: int


class MatchClockState:
    """Main-time + per-move countdown clock for CAM/XANH.

    When main time reaches zero, the configured countdown acts like a simple
    byoyomi period that resets at the beginning of each turn.
    """

    def __init__(self):
        self._clocks: Dict[Player, SideClock] = {
            Player.CAM: SideClock(0, 0, 0),
            Player.XANH: SideClock(0, 0, 0),
        }

    def configure_side(self, player: Player, *, hours: int, minutes: int, countdown_s: int) -> None:
        main_ms = max(0, (int(hours) * 3600 + int(minutes) * 60) * 1000)
        period_ms = max(0, int(countdown_s) * 1000)
        self._clocks[player] = SideClock(main_ms, period_ms, period_ms)

    def start_turn(self, player: Player) -> None:
        clock = self._clocks[player]
        if clock.main_ms <= 0:
            clock.period_remaining_ms = clock.period_ms

    def consume(self, player: Player, elapsed_ms: int) -> bool:
        """Consume elapsed time; return True when the player flags."""
        remaining = max(0, int(elapsed_ms))
        clock = self._clocks[player]

        if remaining <= 0:
            return self.flagged(player)

        if clock.main_ms > 0:
            used = min(clock.main_ms, remaining)
            clock.main_ms -= used
            remaining -= used
            if clock.main_ms <= 0 and clock.period_remaining_ms <= 0:
                clock.period_remaining_ms = clock.period_ms

        if remaining > 0 and clock.main_ms <= 0:
            if clock.period_ms <= 0:
                # Untimed side: 0 main + 0 countdown.
                clock.period_remaining_ms = 0
                return False
            clock.period_remaining_ms = max(0, clock.period_remaining_ms - remaining)

        return self.flagged(player)

    def flagged(self, player: Player) -> bool:
        clock = self._clocks[player]
        # 0 main + 0 countdown is treated as an untimed game.
        if clock.main_ms <= 0 and clock.period_ms <= 0:
            return False
        if clock.main_ms > 0:
            return False
        return clock.period_remaining_ms <= 0

    def remaining_for(self, player: Player) -> int:
        clock = self._clocks[player]
        return clock.main_ms if clock.main_ms > 0 else clock.period_remaining_ms

    def main_remaining_for(self, player: Player) -> int:
        return self._clocks[player].main_ms

    def period_remaining_for(self, player: Player) -> int:
        return self._clocks[player].period_remaining_ms

    def period_for(self, player: Player) -> int:
        return self._clocks[player].period_ms

    def display(self, player: Player) -> str:
        clock = self._clocks[player]
        if clock.main_ms > 0:
            total_s = (clock.main_ms + 999) // 1000
            h, rem = divmod(total_s, 3600)
            m, s = divmod(rem, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        if clock.period_ms > 0:
            seconds = max(0.0, clock.period_remaining_ms / 1000.0)
            return f"Byo {seconds:04.1f}s"
        return "∞"


def winner_from_result(result: str | None):
    """Extract a winner from the project's human-readable result text.

    Returns Player.CAM / Player.XANH or None when no winner can be inferred.

    Some terminal results explicitly contain ``CAM/XANH thang`` (checkmate,
    PAT, resignation, timeout, engine error).  Thiên Nhật Thủ currently stores
    only the loser, e.g. ``CAM thua (Thien Nhat Thu - ...)``.  In that case the
    winner is the opposite side.
    """
    text = " ".join((result or "").upper().split())
    if not text:
        return None

    # Prefer an explicitly named winner whenever the result contains one.
    cam_win = "CAM THANG" in text
    xanh_win = "XANH THANG" in text
    if cam_win and not xanh_win:
        return Player.CAM
    if xanh_win and not cam_win:
        return Player.XANH

    # Fallback for results that name only the loser, notably Thiên Nhật Thủ.
    # Keep this deliberately narrow: the side token must begin the result and
    # be followed by a losing phrase, so unrelated comments do not affect the
    # continuous-series scoreboard.
    cam_lost = text.startswith("CAM THUA ") or text.startswith("CAM THUA(")
    xanh_lost = text.startswith("XANH THUA ") or text.startswith("XANH THUA(")
    if cam_lost and not xanh_lost:
        return Player.XANH
    if xanh_lost and not cam_lost:
        return Player.CAM

    return None


class SeriesScore:
    """Small scoreboard for continuous games."""

    def __init__(self):
        self.cam_wins = 0
        self.xanh_wins = 0
        self.other = 0
        self.games = 0

    def reset(self) -> None:
        self.cam_wins = 0
        self.xanh_wins = 0
        self.other = 0
        self.games = 0

    def record(self, result: str | None) -> None:
        winner = winner_from_result(result)
        self.games += 1
        if winner == Player.CAM:
            self.cam_wins += 1
        elif winner == Player.XANH:
            self.xanh_wins += 1
        else:
            self.other += 1

    def summary(self) -> str:
        parts = [f"Cam {self.cam_wins}", f"Xanh {self.xanh_wins}"]
        if self.other:
            parts.append(f"Other {self.other}")
        return " | ".join(parts)
