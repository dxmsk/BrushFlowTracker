"""Small persistence primitive: coalesce saves without dropping a newer revision."""

from threading import Lock
from typing import Callable


class CoalescingWriter:
    """One writer, short bookkeeping lock, and a remembered dirty revision.

    The callback owns snapshot creation. Slow storage never holds this lock;
    a concurrent request marks the next revision and the active writer drains
    it before returning. Failed writes remain dirty for an explicit retry.
    """

    def __init__(self) -> None:
        self._guard = Lock()
        self._requested = 0
        self._written = 0
        self._active = False

    @property
    def dirty(self) -> bool:
        with self._guard:
            return self._written < self._requested

    def save(self, callback: Callable[[], None]) -> bool:
        with self._guard:
            self._requested += 1
            if self._active:
                return False
            self._active = True
        while True:
            with self._guard:
                revision = self._requested
            try:
                callback()
            except BaseException:
                with self._guard:
                    self._active = False
                raise
            with self._guard:
                self._written = revision
                if self._requested == revision:
                    self._active = False
                    return True
