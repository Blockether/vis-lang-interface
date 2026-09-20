"""Running a toolchain program reports its output, status and absence."""

import sys

import blockether.vis.extension as vis
import pytest

from vis_lang_interface import ToolMissing, ToolTimeout, process


def test_run_captures_output_and_status():
    done = process.run([sys.executable, "-c", "print('hi')"])
    assert done.exit_code == 0
    assert done.out.strip() == "hi"
    assert done.is_ok is True
    assert done.duration_ms >= 0


def test_run_reports_a_failing_status():
    done = process.run([sys.executable, "-c", "raise SystemExit(3)"])
    assert done.exit_code == 3
    assert done.is_ok is False


def test_run_reads_stdin():
    done = process.run(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        stdin="abc",
    )
    assert done.out.strip() == "ABC"


def test_the_two_streams_stay_apart():
    """A pty would merge them; a tool's output is data, so each keeps its own file."""
    done = process.run(
        [
            sys.executable,
            "-c",
            "import sys, json; sys.stdout.write(json.dumps({'ok': True}));"
            " sys.stderr.write('noise')",
        ]
    )
    assert done.out == '{"ok": true}'
    assert done.err == "noise"


def test_run_applies_one_calls_environment():
    done = process.run(
        [sys.executable, "-c", "import os; print(os.environ['VIS_LANG_PROBE'])"],
        env={"VIS_LANG_PROBE": "set-for-this-run"},
    )
    assert done.out.strip() == "set-for-this-run"


def test_missing_program_names_itself():
    with pytest.raises(ToolMissing, match="vis-no-such-tool"):
        process.run(["vis-no-such-tool"])


def test_tool_path_includes_the_install_hint():
    with pytest.raises(ToolMissing, match="install it with brew"):
        process.tool_path("vis-no-such-tool", "install it with brew")


def test_timeout_names_the_program():
    with pytest.raises(ToolTimeout, match="did not finish"):
        process.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=1)


def test_inside_vis_every_child_goes_through_the_jail(monkeypatch):
    """`vis.outside` exists only where there is no Vis host to confine anything."""
    assert process.shell_call() is vis.shell
    monkeypatch.delattr(vis, "outside")
    assert process.shell_call() is vis.jailed_shell


def _recorded(monkeypatch):
    """The options every child of this test is started with."""
    seen = []
    started = vis.shell

    def recording(options):
        seen.append(dict(options))
        return started(options)

    monkeypatch.setattr(vis, "shell", recording)
    return seen


def test_a_run_grants_only_its_own_directory_by_default(monkeypatch):
    seen = _recorded(monkeypatch)
    done = process.run([sys.executable, "-c", "print('hi')"])
    assert done.is_ok is True
    granted = seen[0]["allow_read_write"]
    assert len(granted) == 1
    assert process.RUN_PREFIX in granted[0]


def test_a_run_carries_the_paths_its_caller_named(monkeypatch, tmp_path):
    """A toolchain reaches its own dependency cache only when the run grants it."""
    cache = tmp_path / "cache"
    cache.mkdir()
    seen = _recorded(monkeypatch)
    done = process.run([sys.executable, "-c", "print('hi')"], read_write=[cache])
    assert done.is_ok is True
    granted = seen[0]["allow_read_write"]
    assert str(cache) in granted
    assert len(granted) == 2
    assert process.RUN_PREFIX in granted[0]
