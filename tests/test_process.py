"""Running a toolchain program reports its output, status and absence."""

import sys

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


def test_missing_program_names_itself():
    with pytest.raises(ToolMissing, match="vis-no-such-tool"):
        process.run(["vis-no-such-tool"])


def test_tool_path_includes_the_install_hint():
    with pytest.raises(ToolMissing, match="install it with brew"):
        process.tool_path("vis-no-such-tool", "install it with brew")


def test_timeout_names_the_program():
    with pytest.raises(ToolTimeout, match="did not finish"):
        process.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout_s=0.2)
