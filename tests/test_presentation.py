"""Every language binding renders the same states the same way."""

import blockether.vis.extension as vis
import pytest

from vis_lang_interface import (
    BuildArtifact,
    BuildResult,
    Diagnostic,
    FormatResult,
    LintResult,
    ReplResult,
    ReplSession,
    TestFailure,
    TestResult,
    presentation,
)


def test_clean_lint_summarizes_the_file_count():
    shown = presentation.lint_presentation(
        "Lint Clojure code", LintResult.of("clojure", [], files=1)
    )
    assert shown.summary == "no findings in 1 file"
    assert shown.content == ()
    uncounted = presentation.lint_presentation(
        "Lint Clojure code", LintResult.of("clojure", [])
    )
    assert uncounted.summary == "no findings"


def test_lint_findings_in_one_directory_form_one_table():
    result = LintResult.of(
        "clojure",
        [Diagnostic("a.clj", 3, 1, "error", "unresolved symbol", "unresolved-symbol")],
        files=2,
    )
    shown = presentation.lint_presentation("Lint Clojure code", result)
    assert shown.summary == "1 error in 1 of 2 files"
    assert shown.content[0].rows[0] == (
        "a.clj:3",
        "error",
        "unresolved-symbol",
        "unresolved symbol",
    )
    assert shown.sections == ()


def test_lint_findings_are_grouped_by_directory():
    result = LintResult.of(
        "python",
        [
            Diagnostic("src/app/core.py", 3, 1, "error", "undefined name", "F821"),
            Diagnostic("src/app/util.py", 8, 5, "warning", "unused import", "F401"),
            Diagnostic("tests/test_core.py", 2, 1, "warning", "unused import", "F401"),
            Diagnostic("tests/test_core.py", 9, 1, "warning", "unused name", "F841"),
            Diagnostic("setup.py", 1, 1, "info", "missing docstring", "D100"),
        ],
        files=6,
    )
    shown = presentation.lint_presentation("Lint Python code", result)
    assert shown.summary == "1 error, 3 warnings, 1 info in 4 of 6 files"
    assert shown.content == ()
    assert [(section.headline, section.summary) for section in shown.sections] == [
        (".", "1 info in setup.py"),
        ("src/app", "1 error, 1 warning in 2 files"),
        ("tests", "2 warnings in test_core.py"),
    ]
    assert [row[0] for row in shown.sections[2].content[0].rows] == [
        "test_core.py:2",
        "test_core.py:9",
    ]


def test_lint_cuts_are_labelled(monkeypatch):
    monkeypatch.setattr(presentation, "MAX_FINDINGS", 2)
    monkeypatch.setattr(presentation, "MAX_SECTIONS", 1)
    unused = [Diagnostic("a.clj", line, 1, "warning", "unused") for line in (1, 2, 3)]
    one = presentation.lint_presentation(
        "Lint Clojure code", LintResult.of("clojure", unused, files=1)
    )
    assert len(one.content[0].rows) == 2
    assert one.content[1].text == "Showing the first 2 of 3 findings."
    spread = [
        Diagnostic("src/a.clj", 1, 1, "warning", "unused"),
        Diagnostic("test/a.clj", 1, 1, "warning", "unused"),
    ]
    two = presentation.lint_presentation(
        "Lint Clojure code", LintResult.of("clojure", spread, files=2)
    )
    assert [section.headline for section in two.sections] == ["src"]
    assert two.content[0].text == "Showing the first 1 of 2 directories."


def test_format_reports_what_changed():
    shown = presentation.format_presentation(
        "Format Clojure code",
        FormatResult("clojure", ("a.clj",), ("b.clj",), is_written=True),
    )
    assert shown.summary == "1 file rewritten"


def test_each_failing_test_is_its_own_section():
    result = TestResult.of(
        "python",
        total=3,
        passed=1,
        failed=2,
        skipped=0,
        duration_ms=1500,
        failures=[
            TestFailure("test_add", "test_math.py", 12, "assert 1 == 2"),
            TestFailure(
                "test_div",
                "test_math.py",
                20,
                "ZeroDivisionError: division by zero\n  in divide()",
            ),
        ],
        output="F.F\n2 failed, 1 passed in 1.50s",
    )
    shown = presentation.test_presentation("Run Python tests", result)
    assert shown.summary == "2 failed, 1 passed in 1.5 s"
    assert shown.content == ()
    add, div = shown.sections
    assert (add.headline, add.summary, add.content) == (
        "test_add",
        "test_math.py:12 · assert 1 == 2",
        (),
    )
    assert div.summary == "test_math.py:20 · ZeroDivisionError: division by zero"
    assert isinstance(div.content[0], vis.ActivityCode)
    assert div.content[0].text.endswith("in divide()")


def test_a_passing_run_shows_only_its_counts():
    result = TestResult.of(
        "python",
        total=3,
        passed=2,
        failed=0,
        skipped=1,
        duration_ms=10,
        output="..s\n2 passed, 1 skipped in 0.01s",
    )
    shown = presentation.test_presentation("Run Python tests", result)
    assert shown.summary == "2 passed, 1 skipped in 0.0 s"
    assert (shown.content, shown.sections) == ((), ())
    nothing = TestResult.of(
        "python", total=0, passed=0, failed=0, skipped=0, duration_ms=0
    )
    shown = presentation.test_presentation("Run Python tests", nothing)
    assert shown.summary == "no tests ran in 0.0 s"


def test_a_failed_run_without_named_failures_shows_its_output():
    result = TestResult.of(
        "clojure",
        total=1,
        passed=0,
        failed=1,
        skipped=0,
        duration_ms=900,
        output="Syntax error compiling at (app/core.clj:3:1).",
    )
    shown = presentation.test_presentation("Run Clojure tests", result)
    assert shown.summary == "1 failed in 0.9 s"
    assert shown.sections == ()
    assert shown.content[0].text == "Syntax error compiling at (app/core.clj:3:1)."


def test_failing_test_cuts_are_labelled(monkeypatch):
    monkeypatch.setattr(presentation, "MAX_SECTIONS", 1)
    failures = [TestFailure(f"test_{n}", "t.py", n, "boom") for n in (1, 2)]
    result = TestResult.of(
        "python",
        total=2,
        passed=0,
        failed=2,
        skipped=0,
        duration_ms=5,
        failures=failures,
    )
    shown = presentation.test_presentation("Run Python tests", result)
    assert [section.headline for section in shown.sections] == ["test_1"]
    assert shown.content[0].text == "Showing the first 1 of 2 failing tests."


def test_a_long_failure_stays_one_line_with_the_whole_message_behind_it():
    message = "expected " + "测" * 400
    result = TestResult.of(
        "python",
        total=1,
        passed=0,
        failed=1,
        skipped=0,
        duration_ms=5,
        failures=[TestFailure("", "t.py", 1, message)],
    )
    (section,) = presentation.test_presentation("Run Python tests", result).sections
    assert section.headline == "t.py"
    assert section.summary.endswith("…")
    assert len(section.summary.encode("utf-8")) <= 512
    assert section.content[0].text == message


def test_build_lists_its_artifacts():
    shown = presentation.build_presentation(
        "Build Python package",
        BuildResult.of(
            "python",
            "wheel",
            artifacts=[BuildArtifact("dist/app-1.0.0-py3-none-any.whl", "wheel", 4200)],
            duration_ms=2500,
        ),
    )
    assert shown.summary == "1 artifact in 2.5 s"
    assert shown.content[0].rows[0] == (
        "dist/app-1.0.0-py3-none-any.whl",
        "wheel",
        "4.2 kB",
    )


def test_failed_build_shows_what_the_toolchain_reported():
    shown = presentation.build_presentation(
        "Build Clojure uberjar",
        BuildResult.of(
            "clojure",
            "uberjar",
            diagnostics=[Diagnostic("src/app.clj", 12, 3, "error", "Syntax error")],
            duration_ms=800,
        ),
    )
    assert shown.summary == "build failed in 0.8 s"
    assert shown.content[0].rows[0][0] == "src/app.clj:12"


def test_build_without_artifacts_says_so():
    shown = presentation.build_presentation(
        "Build Python package", BuildResult.of("python", "wheel", duration_ms=100)
    )
    assert shown.summary == "nothing to build in 0.1 s"
    assert shown.content == ()


def test_repl_error_is_shown_instead_of_a_value():
    shown = presentation.repl_presentation(
        "Evaluate in Python REPL",
        ReplResult("python", "~/app", "", "", "NameError: x", 12, True),
    )
    assert shown.summary == "evaluation failed"
    assert "NameError" in shown.content[0].text


def test_a_session_says_what_happened_in_its_summary_alone():
    session = ReplSession(
        "clojure",
        "nrepl:~/app",
        "~/app",
        "clojure -M:nrepl",
        True,
        "started · port 7888 · pid 42",
    )
    shown = presentation.session_presentation("Start nREPL", session)
    assert shown.summary == "nrepl:~/app · started · port 7888 · pid 42"
    assert (shown.content, shown.sections) == ((), ())


def test_a_session_without_detail_reads_as_its_state():
    sessions = [
        ReplSession("python", "~/app", "~/app", "python3", is_running)
        for is_running in (True, False)
    ]
    summaries = [
        presentation.session_presentation("Check Python REPL", session).summary
        for session in sessions
    ]
    assert summaries == ["~/app · running", "~/app · not running"]


def test_renderer_covers_start_success_and_failure():
    render = presentation.renderer(
        "Lint Clojure code",
        lambda result: presentation.lint_presentation("Lint Clojure code", result),
    )
    assert render(phase="start") is None
    assert render(phase="success", result=LintResult.of("clojure", [], files=1))
    failed = render(phase="failure", error=RuntimeError("clj-kondo is not on PATH"))
    assert failed.summary == "failed"
    assert "clj-kondo" in failed.content[0].text


def _lint(*levels):
    findings = [Diagnostic("a.clj", 3, 1, level, "unused binding") for level in levels]
    return presentation.lint_presentation(
        "Lint Clojure code", LintResult.of("clojure", findings, files=1)
    )


def _tests(failed):
    result = TestResult.of(
        "python", total=2, passed=2 - failed, failed=failed, skipped=0, duration_ms=10
    )
    return presentation.test_presentation("Run Python tests", result)


@pytest.mark.skipif(
    not presentation._REPORTS_VERDICT, reason="this Vis SDK predates check verdicts"
)
def test_checks_tell_vis_whether_they_passed():
    assert [_lint().verdict, _lint("warning").verdict] == ["passed", "failed"]
    assert [_tests(0).verdict, _tests(1).verdict] == ["passed", "failed"]
    assert _tests(1).to_wire()["verdict"] == "failed"


def test_checks_render_on_hosts_without_verdicts(monkeypatch):
    monkeypatch.setattr(presentation, "_REPORTS_VERDICT", False)
    shown = _tests(1)
    assert shown.summary == "1 failed, 1 passed in 0.0 s"
    assert "verdict" not in shown.to_wire()
