"""RoundGuard: per-session round bookkeeping for interruption safety.

Design (see README "interruption flow"):
- every user turn gets a monotonically increasing round_id
- a round is "dead" once a newer round has begun or the user interrupted;
  the server stops emitting events for dead rounds, and the client ALSO
  drops any event whose round_id is not newer than what it has accepted.
  Double filtering guarantees stale network responses can never repaint
  the scene or restart playback."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoundMetrics:
    round_id: int
    text: str = ""
    llm_ms: int = 0
    tts_first_ms: int = 0
    total_ms: int = 0
    interrupted: bool = False
    error: str = ""


@dataclass
class RoundGuard:
    current_round: int = 0
    dead_rounds: set[int] = field(default_factory=set)
    metrics: list[RoundMetrics] = field(default_factory=list)
    _current: RoundMetrics | None = None

    def begin(self, text: str) -> int:
        self.current_round += 1
        self._current = RoundMetrics(round_id=self.current_round, text=text[:120])
        self.metrics.append(self._current)
        if len(self.metrics) > 200:
            self.metrics = self.metrics[-200:]
        return self.current_round

    def is_dead(self, round_id: int) -> bool:
        return round_id != self.current_round or round_id in self.dead_rounds

    def mark_interrupted(self, upto: int) -> int:
        """Mark every round <= upto dead/interrupted. Returns count."""
        n = 0
        for m in self.metrics:
            if m.round_id <= upto and not m.interrupted:
                m.interrupted = True
                self.dead_rounds.add(m.round_id)
                n += 1
        return n

    def patch(self, **kw) -> None:
        if self._current:
            for k, v in kw.items():
                setattr(self._current, k, v)
