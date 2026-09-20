"""A runtime outlives its call, answers on its rendezvous, and can be ended."""

import json
import sys
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
