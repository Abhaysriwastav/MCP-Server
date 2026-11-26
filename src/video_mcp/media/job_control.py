"""Thread-safe pause, resume, and cancel controller for active render jobs."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from dataclasses import dataclass, field


class RenderCancelledError(RuntimeError):
    """Raised when an active render job is cancelled by the user."""


@dataclass
class JobControlHandle:
    """Per-job synchronization handle for pause/resume/cancel and subprocess PIDs."""

    job_id: str
    _pause_gate: threading.Event = field(default_factory=threading.Event)
    _cancel_event: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _pids: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self._pause_gate.set()  # Unpaused by default

    def register_pid(self, pid: int) -> None:
        with self._lock:
            self._pids.add(pid)
            if not self._pause_gate.is_set() and hasattr(signal, "SIGSTOP"):
                try:
                    os.kill(pid, signal.SIGSTOP)
                except OSError:
                    pass

    def unregister_pid(self, pid: int) -> None:
        with self._lock:
            self._pids.discard(pid)

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def pause(self) -> None:
        self._pause_gate.clear()
        if hasattr(signal, "SIGSTOP"):
            with self._lock:
                for pid in list(self._pids):
                    try:
                        os.kill(pid, signal.SIGSTOP)
                    except OSError:
                        pass

    def resume(self) -> None:
        self._pause_gate.set()
        if hasattr(signal, "SIGCONT"):
            with self._lock:
                for pid in list(self._pids):
                    try:
                        os.kill(pid, signal.SIGCONT)
                    except OSError:
                        pass

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_gate.set()
        with self._lock:
            for pid in list(self._pids):
                try:
                    if hasattr(signal, "SIGCONT"):
                        os.kill(pid, signal.SIGCONT)
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

    async def checkpoint(self) -> None:
        """Pause if requested, or raise RenderCancelledError if cancelled."""
        while not self._pause_gate.is_set():
            if self._cancel_event.is_set():
                raise RenderCancelledError(f"Job '{self.job_id}' was cancelled.")
            await asyncio.sleep(0.2)
        if self._cancel_event.is_set():
            raise RenderCancelledError(f"Job '{self.job_id}' was cancelled.")


class RenderController:
    """Registry of active JobControlHandle instances keyed by job_id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handles: dict[str, JobControlHandle] = {}

    def create_handle(self, job_id: str) -> JobControlHandle:
        with self._lock:
            handle = JobControlHandle(job_id=job_id)
            self._handles[job_id] = handle
            return handle

    def get_handle(self, job_id: str) -> JobControlHandle | None:
        with self._lock:
            return self._handles.get(job_id)

    def remove_handle(self, job_id: str) -> None:
        with self._lock:
            self._handles.pop(job_id, None)
