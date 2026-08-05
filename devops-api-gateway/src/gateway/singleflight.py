"""Thread-safe bounded single-flight refresh coordination."""

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Condition, Lock
from time import monotonic


@dataclass(slots=True)
class _Flight:
    condition: Condition = field(default_factory=Condition)
    complete: bool = False
    result: dict[str, object] | None = None


class RefreshSingleFlight:
    """Coalesce concurrent refreshes by opaque refresh-token digest key."""

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._lock = Lock()
        self._flights: dict[str, _Flight] = {}

    def run(self, key: str, operation: Callable[[], dict[str, object] | None]) -> dict[str, object] | None:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = _Flight()
                self._flights[key] = flight
        if leader:
            try:
                result = operation()
                with flight.condition:
                    flight.result = result
                    flight.complete = True
                    flight.condition.notify_all()
                return result
            finally:
                with self._lock:
                    self._flights.pop(key, None)
        deadline = monotonic() + self.timeout_seconds
        with flight.condition:
            while not flight.complete:
                remaining = deadline - monotonic()
                if remaining <= 0 or not flight.condition.wait(remaining):
                    return None
            return flight.result
