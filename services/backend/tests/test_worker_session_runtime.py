"""Process monitoring never claims provider work or stores exception details."""

from types import SimpleNamespace
from typing import Any

import pytest

from alphasense import document_task_worker, task_worker
from alphasense import worker_session_runtime as runtime
from alphasense.db import StoreUnavailable


class StoreSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.start_error = False
        self.pulse_error = False
        self.stop_error = False

    def start(self, registration: Any) -> None:
        self.calls.append(("start", registration))
        if self.start_error:
            raise StoreUnavailable("secret registration detail")

    def heartbeat(self, session_id: Any) -> None:
        self.calls.append(("heartbeat", session_id))
        if self.pulse_error:
            raise StoreUnavailable("secret heartbeat detail")

    def stop(self, session_id: Any, reason: str, error_code: Any) -> None:
        self.calls.append(("stop", session_id, reason, error_code))
        if self.stop_error:
            raise StoreUnavailable("secret shutdown detail")


class ThreadSpy:
    def __init__(self, **_kwargs: Any) -> None:
        self.alive = False
        self.joined = False

    def start(self) -> None:
        pass

    def join(self, timeout: float) -> None:
        assert timeout < 10
        self.joined = True

    def is_alive(self) -> bool:
        return self.alive


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> StoreSpy:
    store = StoreSpy()
    monkeypatch.setattr(runtime, "WorkerSessionStore", lambda _engine: store)
    monkeypatch.setattr(runtime, "runtime_fingerprint", lambda _kind: "a" * 64)
    monkeypatch.setattr(runtime, "Thread", ThreadSpy)
    return store


def monitor() -> runtime.WorkerSessionMonitor:
    return runtime.WorkerSessionMonitor(object(), "safe-worker", "document_validation", "forever")  # type: ignore[arg-type]


def test_normal_lifetime_has_unique_boot_identity_and_clean_close(spy: StoreSpy) -> None:
    first, second = monitor(), monitor()
    assert first.registration.session_id != second.registration.session_id
    with first:
        first.check()
        first.wait(0)
    assert first._thread.joined  # type: ignore[attr-defined]
    assert spy.calls[-1] == ("stop", first.registration.session_id, "completed", None)
    assert first.registration.process_id > 0


@pytest.mark.parametrize(
    "failure,reason,code",
    [
        (KeyboardInterrupt(), "interrupted", None),
        (ValueError("private source body"), "error", "WORKER_RUNTIME_FAILED"),
    ],
)
def test_original_failure_preserved_and_only_fixed_metadata_stored(
    spy: StoreSpy, failure: BaseException, reason: str, code: str | None
) -> None:
    spy.stop_error = True
    session = monitor()
    with pytest.raises(type(failure)) as caught, session:
        raise failure
    assert caught.value is failure
    assert spy.calls[-1] == ("stop", session.registration.session_id, reason, code)
    assert "private source body" not in repr(spy.calls)


def test_clean_exit_with_failed_stop_is_redacted_and_not_success(spy: StoreSpy) -> None:
    spy.stop_error = True
    with pytest.raises(runtime.WorkerMonitorFailed, match="^Worker monitoring unavailable$"):
        with monitor():
            pass


def test_heartbeat_failure_stops_more_claims_and_records_monitor_code(spy: StoreSpy) -> None:
    session = monitor()
    spy.pulse_error = True

    class OnePulse:
        def wait(self, interval: float) -> bool:
            assert interval == 10
            return False

    with pytest.raises(runtime.WorkerMonitorFailed), session:
        original_stop = session._stop
        session._stop = OnePulse()  # type: ignore[assignment]
        session._heartbeat()
        session._stop = original_stop
        session.wait(0)
    assert spy.calls[-1][-2:] == ("error", "WORKER_MONITOR_FAILED")
    assert "secret heartbeat detail" not in repr(spy.calls)


def test_blocked_heartbeat_shutdown_does_not_race_terminal_write(spy: StoreSpy) -> None:
    session = monitor()
    session._thread.alive = True  # type: ignore[attr-defined]
    with pytest.raises(runtime.WorkerMonitorFailed), session:
        pass
    assert all(call[0] != "stop" for call in spy.calls)


@pytest.mark.parametrize(
    "module,process_name,kind",
    [
        (task_worker, "process_task_once", "sec_import"),
        (document_task_worker, "process_document_once", "document_validation"),
    ],
)
def test_once_idle_registers_before_claim_and_stops(
    spy: StoreSpy, monkeypatch: pytest.MonkeyPatch, module: Any, process_name: str, kind: str
) -> None:
    monkeypatch.setattr(
        module, "get_store", lambda: SimpleNamespace(engine=object(), check_ready=lambda: None)
    )

    def idle(_engine: Any, _worker_id: str) -> bool:
        assert spy.calls[0][0] == "start"
        spy.calls.append(("claim",))
        return False

    monkeypatch.setattr(module, process_name, idle)
    assert module.main(["--once", "--worker-id", "safe-worker"]) == 0
    registration = spy.calls[0][1]
    assert registration.kind == kind and registration.mode == "once"
    assert [call[0] for call in spy.calls] == ["start", "claim", "stop"]
    assert spy.calls[-1][-2:] == ("completed", None)


@pytest.mark.parametrize("module", [task_worker, document_task_worker])
def test_failed_registration_prevents_queue_work(
    spy: StoreSpy, monkeypatch: pytest.MonkeyPatch, module: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    spy.start_error = True
    monkeypatch.setattr(
        module, "get_store", lambda: SimpleNamespace(engine=object(), check_ready=lambda: None)
    )
    monkeypatch.setattr(
        module,
        "process_task_once" if module is task_worker else "process_document_once",
        lambda *_args: pytest.fail("Registration failed before claim"),
    )
    assert module.main(["--once"]) == 1
    assert "secret" not in capsys.readouterr().out
    assert all(call[0] != "stop" for call in spy.calls)
