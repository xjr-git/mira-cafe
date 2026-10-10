"""Session state: conversation history + story-graph node.

For this interview MVP there is one global session (no account system is
required by the spec). POST /api/reset clears it."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

NODES = {"opening", "smalltalk", "confide", "reveal", "ending"}


@dataclass
class Session:
    node: str = "opening"
    history: list[dict] = field(default_factory=list)   # {"role","content"}
    media_shown: int = 0                                 # polaroids revealed
    rain_stopped: bool = False
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_history(self, role: str, content: str) -> None:
        with self._lock:
            self.history.append({"role": role, "content": content})
            if len(self.history) > 24:
                self.history = self.history[-24:]

    def goto(self, node: str) -> None:
        if node in NODES:
            self.node = node

    def reset(self) -> None:
        self.node = "opening"
        self.history.clear()
        self.media_shown = 0
        self.rain_stopped = False
        self.started_at = time.time()


SESSION = Session()
