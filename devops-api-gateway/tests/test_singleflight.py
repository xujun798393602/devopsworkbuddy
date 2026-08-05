from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

from gateway.singleflight import RefreshSingleFlight


def test_concurrent_refresh_is_coalesced_and_then_evicted() -> None:
    flight = RefreshSingleFlight(timeout_seconds=1)
    calls = 0
    lock = Lock()

    def refresh():
        nonlocal calls
        with lock:
            calls += 1
        sleep(0.05)
        return {"access_token": "new"}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _value: flight.run("family", refresh), range(8)))
    assert calls == 1
    assert all(item == {"access_token": "new"} for item in results)
    assert flight.run("family", refresh) == {"access_token": "new"}
    assert calls == 2


def test_failed_refresh_releases_waiters_and_allows_retry() -> None:
    flight = RefreshSingleFlight(timeout_seconds=1)
    calls = 0
    lock = Lock()

    def failed():
        nonlocal calls
        with lock:
            calls += 1
        sleep(0.05)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _value: flight.run("family", failed), range(5)))
    assert calls == 1 and results == [None] * 5
    assert flight.run("family", lambda: {"access_token": "retry"}) == {"access_token": "retry"}
