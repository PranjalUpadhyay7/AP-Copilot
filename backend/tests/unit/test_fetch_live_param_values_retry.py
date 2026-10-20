from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.knowledge.metadata_fetcher import fetch_live_param_values


class _FakeParamValue(SimpleNamespace):
    pass


class _FakeMav:
    def __init__(self, all_params: dict[int, tuple[str, float]], dropped_on_sweep: set[int]):
        self._all_params = all_params
        self._dropped_on_sweep = set(dropped_on_sweep)
        self._queue: list[_FakeParamValue] = []
        self.list_requests = 0
        self.read_requests: list[int] = []
        self.call_log: list[tuple] = []

    def param_request_list_send(self, target_system, target_component):
        self.list_requests += 1
        count = len(self._all_params)
        for idx, (name, value) in self._all_params.items():
            if idx in self._dropped_on_sweep:
                continue
            self._queue.append(_FakeParamValue(param_id=name, param_value=value, param_count=count, param_index=idx))

    def param_request_read_send(self, target_system, target_component, param_id, param_index):
        self.read_requests.append(param_index)
        self.call_log.append(("send", param_index))
        # Simulates recovery: a re-request for a dropped index succeeds.
        if param_index in self._all_params:
            name, value = self._all_params[param_index]
            count = len(self._all_params)
            self._queue.append(_FakeParamValue(param_id=name, param_value=value, param_count=count, param_index=param_index))


class _FakeConn:
    def __init__(self, all_params: dict[int, tuple[str, float]], dropped_on_sweep: set[int]):
        self.target_system = 1
        self.target_component = 1
        self.mav = _FakeMav(all_params, dropped_on_sweep)

    def recv_match(self, type, blocking, timeout):
        self.mav.call_log.append(("recv",))
        if self.mav._queue:
            return self.mav._queue.pop(0)
        return None


def _params(n: int) -> dict[int, tuple[str, float]]:
    return {i: (f"PARAM_{i}", float(i)) for i in range(n)}


def test_no_drops_completes_on_the_first_sweep():
    conn = _FakeConn(_params(50), dropped_on_sweep=set())
    values = fetch_live_param_values(conn, timeout=5.0)
    assert len(values) == 50
    assert conn.mav.read_requests == []  # never needed a retry


def test_dropped_params_are_recovered_via_individual_retry():
    conn = _FakeConn(_params(50), dropped_on_sweep={3, 17, 42})
    values = fetch_live_param_values(conn, timeout=5.0)
    assert len(values) == 50
    assert values["PARAM_3"] == 3.0
    assert values["PARAM_17"] == 17.0
    assert values["PARAM_42"] == 42.0
    # Retried exactly the missing ones, not a blind full re-sweep.
    assert set(conn.mav.read_requests) == {3, 17, 42}


def test_heavy_loss_recovers_within_the_retry_budget():
    dropped = set(range(0, 1408, 2))  # half of a realistic 1408-param set
    conn = _FakeConn(_params(1408), dropped_on_sweep=dropped)
    values = fetch_live_param_values(conn, timeout=10.0)
    assert len(values) == 1408


def test_retry_requests_are_paced_in_small_batches_not_blasted_at_once():
    from app.knowledge.metadata_fetcher import _PARAM_REQUEST_READ_BATCH_SIZE

    dropped = set(range(0, 1408, 2))  # half of a realistic 1408-param set
    conn = _FakeConn(_params(1408), dropped_on_sweep=dropped)
    fetch_live_param_values(conn, timeout=10.0)

    longest_unbroken_send_run = 0
    current_run = 0
    for entry in conn.mav.call_log:
        if entry[0] == "send":
            current_run += 1
            longest_unbroken_send_run = max(longest_unbroken_send_run, current_run)
        else:
            current_run = 0
    assert longest_unbroken_send_run <= _PARAM_REQUEST_READ_BATCH_SIZE
    assert longest_unbroken_send_run < 20  # the real firmware's hard queue cap


def test_a_persistently_unrecoverable_param_still_raises_not_silently_incomplete():
    class _NeverRecoversMav(_FakeMav):
        def param_request_read_send(self, target_system, target_component, param_id, param_index):
            self.read_requests.append(param_index)
            # Index 7 never comes back, no matter how many times it's retried.

    class _NeverRecoversConn(_FakeConn):
        def __init__(self, all_params, dropped_on_sweep):
            self.target_system = 1
            self.target_component = 1
            self.mav = _NeverRecoversMav(all_params, dropped_on_sweep)

    conn = _NeverRecoversConn(_params(20), dropped_on_sweep={7})
    with pytest.raises(TimeoutError, match="19/20"):
        fetch_live_param_values(conn, timeout=3.0, max_retry_rounds=3)
    # Tried the full retry budget, not given up after one attempt.
    assert conn.mav.read_requests.count(7) == 3
