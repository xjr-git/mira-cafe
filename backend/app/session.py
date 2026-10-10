"""Session state: conversation history + story-graph node.

Multi-client concurrency: each browser gets a stable client id (X-Sid
header, generated once and kept in localStorage). Sessions are isolated
per sid - separate story node, history AND RoundGuard, so user B's new
round can never kill user A's in-flight reply (a real bug when the guard
was a global singleton: is_dead() compared against a global counter).

Memory bounds for the small ECS: at most MAX_SESSIONS live sessions
(LRU evict), idle sessions expire after TTL_S. One session is ~ a few KB.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .guard import RoundGuard

NODES = {"opening", "smalltalk", "confide", "reveal", "ending"}

TTL_S = 2 * 60 * 60          # idle session expires after 2h
MAX_SESSIONS = 128           # hard cap; LRU eviction beyond this


@dataclass
class Session:
    sid: str = "anon"
    node: str = "opening"
    history: list[dict] = field(default_factory=list)   # {"role","content"}
    media_shown: int = 0                                 # polaroids revealed
    rain_stopped: bool = False
    started_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    guard: RoundGuard = field(default_factory=RoundGuard)

    def touch(self) -> None:
        self.last_seen = time.time()

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
        self.guard = RoundGuard()


class SessionManager:
    """sid -> Session registry with TTL expiry and LRU cap."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, sid: str) -> Session:
        sid = (sid or "anon")[:64]
        now = time.time()
        with self._lock:
            s = self._sessions.get(sid)
            if s is None:
                if len(self._sessions) >= MAX_SESSIONS:
                    self._evict(now, force=True)
                s = Session(sid=sid)
                self._sessions[sid] = s
            s.touch()
            return s

    def _evict(self, now: float, force: bool = False) -> None:
        # drop idle sessions first; under pressure, drop oldest by last_seen
        for k in [k for k, v in self._sessions.items() if now - v.last_seen > TTL_S]:
            del self._sessions[k]
        if force and len(self._sessions) >= MAX_SESSIONS:
            oldest = sorted(self._sessions.items(), key=lambda kv: kv[1].last_seen)
            for k, _ in oldest[: max(1, len(oldest) // 4)]:
                del self._sessions[k]

    def cleanup(self) -> int:
        with self._lock:
            before = len(self._sessions)
            self._evict(time.time())
            return before - len(self._sessions)

    def all_guards(self) -> list[RoundGuard]:
        with self._lock:
            return [s.guard for s in self._sessions.values()]

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


SM = SessionManager()
# back-compat alias for story.py / llm.py type hints
SESSION = SM.get("anon")
