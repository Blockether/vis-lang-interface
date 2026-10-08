"""A runtime outlives its call, answers on its rendezvous, and can be ended."""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from vis_lang_interface import Runtime, RuntimeGone, ToolMissing, runtime

ECHO = """import sys, json
sys.stderr.write('runtime up\\n')
sys.stderr.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    if request.get('op') == 'quit':
        raise SystemExit(7)
    sys.stdout.write(json.dumps({'id': request.get('id'), 'echo': request}) + '\\n')
    sys.stdout.flush()
"""

SILENT = """import sys
for line in sys.stdin:
    pass
"""

# Answers each request after its `delay`, so a later request can be answered first.
STAGGER = """import sys, json, threading, time
lock = threading.Lock()
def answer(request):
    time.sleep(float(request.get('delay', 0)))
    with lock:
        sys.stdout.write(json.dumps({'id': request.get('id'), 'echo': request}) + '\\n')
        sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if line:
        threading.Thread(target=answer, args=(json.loads(line),)).start()
"""


def driver(tmp_path, source, name="driver.py"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return [sys.executable, str(path)]


@pytest.fixture
def echo(tmp_path):
    live = runtime.start(driver(tmp_path, ECHO), cwd=tmp_path, name="test")
    yield live
    live.stop()


def test_a_runtime_answers_on_its_rendezvous(echo):
    assert isinstance(echo, Runtime)
    assert echo.is_running is True
    assert echo.pid
    answer = echo.request({"op": "ping"}, 10)
    assert answer["echo"] == {"op": "ping"}


def test_globals_of_the_conversation_survive_between_requests(echo):
    assert echo.request({"op": "one"}, 10)["echo"]["op"] == "one"
    assert echo.request({"op": "two"}, 10)["echo"]["op"] == "two"


def test_an_answer_can_be_waited_for_by_id(echo):
    assert echo.request({"op": "ping", "id": "9"}, 10, wants="9")["id"] == "9"


def test_what_the_runtime_prints_stays_readable(echo):
    echo.request({"op": "ping"}, 10)
    deadline = time.time() + 5
    tail = echo.log_tail()
    while "runtime up" not in "\n".join(tail) and time.time() < deadline:
        time.sleep(0.1)
        tail = echo.log_tail()
    assert "runtime up" in "\n".join(tail)


def test_a_runtime_that_stops_mid_call_says_so(echo):
    with pytest.raises(RuntimeGone, match="stopped before answering"):
        echo.request({"op": "quit"}, 10)


def test_a_silent_runtime_times_out(tmp_path):
    live = runtime.start(driver(tmp_path, SILENT), cwd=tmp_path, name="test")
    try:
        with pytest.raises(TimeoutError, match="did not answer"):
            live.request({"op": "ping"}, 1)
    finally:
        live.stop()


def test_stopping_ends_the_runtime(tmp_path):
    live = runtime.start(driver(tmp_path, ECHO), cwd=tmp_path, name="test")
    live.stop()
    assert live.is_running is False
    with pytest.raises(RuntimeGone):
        live.request({"op": "ping"}, 5)


def test_a_missing_runtime_program_names_itself(tmp_path):
    with pytest.raises(ToolMissing, match="vis-no-such-runtime"):
        runtime.start(["vis-no-such-runtime"], cwd=tmp_path)


def test_the_rendezvous_is_removed_with_the_runtime():
    meeting = runtime.Rendezvous("test").open()
    path = Path(meeting.path)
    assert (path / "requests").is_fifo()
    meeting.write(json.dumps({"op": "ping"}))
    meeting.close()
    assert not path.exists()


def test_a_closed_rendezvous_refuses_a_write_like_a_closed_descriptor():
    # Regression: the request end was None after close, so a write raised a
    # TypeError that `Runtime.call` did not turn into RuntimeGone.
    meeting = runtime.Rendezvous("test").open()
    meeting.close()
    with pytest.raises(OSError):
        meeting.write(json.dumps({"op": "ping"}))


def test_a_rendezvous_that_was_never_opened_has_no_lines():
    # Regression: reading before `open` passed None to `select` and raised.
    meeting = runtime.Rendezvous("test")
    try:
        assert list(meeting.lines()) == []
    finally:
        meeting.close()


def test_a_driver_placed_in_the_rendezvous_starts_the_runtime(tmp_path):
    meeting = runtime.Rendezvous("test").open()
    placed = meeting.place("driver.py", ECHO)
    assert Path(placed).parent == Path(meeting.path)
    live = runtime.start([sys.executable, placed], cwd=tmp_path, meeting=meeting)
    try:
        assert live.request({"op": "ping"}, 10)["echo"] == {"op": "ping"}
    finally:
        live.stop()


def test_a_failed_start_closes_the_rendezvous_it_was_given(tmp_path):
    meeting = runtime.Rendezvous("test").open()
    with pytest.raises(ToolMissing):
        runtime.start(["vis-no-such-runtime"], cwd=tmp_path, meeting=meeting)
    assert not Path(meeting.path).exists()


# Regression, user report: a lint waited 57 s for a test run, because each call
# held the whole runtime until its answer came.
def test_calls_with_an_id_wait_only_for_their_own_answer(tmp_path):
    live = runtime.start(driver(tmp_path, STAGGER), cwd=tmp_path, name="test")
    answers = {}
    slow = threading.Thread(
        target=lambda: answers.update(
            slow=live.request({"id": "slow", "delay": 2}, 10, wants="slow")
        )
    )
    try:
        slow.start()
        time.sleep(0.2)
        started = time.monotonic()
        assert live.request({"id": "fast"}, 10, wants="fast")["id"] == "fast"
        assert time.monotonic() - started < 1.5
        slow.join(10)
        assert answers["slow"]["id"] == "slow"
    finally:
        live.stop()


def test_calls_without_an_id_still_run_one_at_a_time(tmp_path):
    live = runtime.start(driver(tmp_path, STAGGER), cwd=tmp_path, name="test")
    answers = {}
    first = threading.Thread(
        target=lambda: answers.update(
            first=live.request({"op": "first", "delay": 1}, 10)
        )
    )
    try:
        first.start()
        time.sleep(0.2)
        assert live.request({"op": "second"}, 10)["echo"]["op"] == "second"
        first.join(10)
        assert answers["first"]["echo"]["op"] == "first"
    finally:
        live.stop()


def test_a_late_answer_reaches_no_later_call(tmp_path):
    live = runtime.start(driver(tmp_path, STAGGER), cwd=tmp_path, name="test")
    try:
        with pytest.raises(TimeoutError):
            live.request({"id": "late", "delay": 1}, 0.3, wants="late")
        time.sleep(1.2)
        assert live.request({"op": "ping"}, 10)["echo"] == {"op": "ping"}
    finally:
        live.stop()


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as stat:
            return stat.read().split(") ", 1)[1][:1] != "Z"
    except OSError:
        return True


def test_a_kept_runtime_outlives_the_process_that_started_it(tmp_path):
    # A sandbox restart ends the Python process that holds the rendezvous. A
    # kept runtime keeps running, and the next start attaches to it.
    command = driver(tmp_path, ECHO)
    first = runtime.start(command, cwd=tmp_path, name="test", shell_id="kept-echo")
    try:
        assert first.request({"op": "one"}, 10)["echo"]["op"] == "one"
        first.detach()
        time.sleep(0.3)
        assert first.is_running is True
        again = runtime.start(command, cwd=tmp_path, name="test", shell_id="kept-echo")
        assert again.pid == first.pid
        assert again.request({"op": "two"}, 10)["echo"]["op"] == "two"
    finally:
        first.stop()
    assert first.is_running is False
    assert not Path(first._meeting.path).exists()


def test_an_answer_written_while_detached_reaches_no_later_call(tmp_path):
    command = driver(tmp_path, STAGGER)
    first = runtime.start(command, cwd=tmp_path, name="test", shell_id="kept-late")
    try:
        with pytest.raises(TimeoutError):
            first.request({"id": "1", "delay": 1}, 0.2, wants="1")
        first.detach()
        time.sleep(1.2)
        again = runtime.start(command, cwd=tmp_path, name="test", shell_id="kept-late")
        assert again.request({"id": "2"}, 10, wants="2")["id"] == "2"
    finally:
        first.stop()


def test_a_kept_runtime_with_another_command_is_replaced(tmp_path):
    first = runtime.start(
        driver(tmp_path, ECHO), cwd=tmp_path, name="test", shell_id="kept-swap"
    )
    first.detach()
    second = runtime.start(
        driver(tmp_path, ECHO, "other.py"),
        cwd=tmp_path,
        name="test",
        shell_id="kept-swap",
    )
    try:
        assert second.pid != first.pid
        # The id now names the new runtime, so ask the old process itself.
        deadline = time.time() + 5
        while _alive(first.pid) and time.time() < deadline:
            time.sleep(0.1)
        assert _alive(first.pid) is False
        assert second.request({"op": "ping"}, 10)["echo"] == {"op": "ping"}
    finally:
        second.stop()


def test_a_runtime_that_is_not_kept_ends_when_its_process_detaches(tmp_path):
    live = runtime.start(driver(tmp_path, ECHO), cwd=tmp_path, name="test")
    live.detach()
    deadline = time.time() + 5
    while live.is_running and time.time() < deadline:
        time.sleep(0.1)
    assert live.is_running is False
