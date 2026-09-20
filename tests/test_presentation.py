"""Every language binding renders the same states the same way."""

from vis_lang_interface import (
    Diagnostic,
    FormatResult,
    LintResult,
    ReplResult,
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


def test_lint_findings_become_a_table():
    result = LintResult.of(
        "clojure",
        [Diagnostic("a.clj", 3, 1, "error", "unresolved symbol", "unresolved-symbol")],
        files=2,
    )
    shown = presentation.lint_presentation("Lint Clojure code", result)
    assert shown.summary == "1 errors, 0 warnings in 2 files"
    assert shown.content[0].rows[0][0] == "a.clj:3"


def test_format_reports_what_changed():
    shown = presentation.format_presentation(
        "Format Clojure code",
        FormatResult("clojure", ("a.clj",), ("b.clj",), is_written=True),
    )
    assert shown.summary == "1 file rewritten"


def test_failing_tests_are_listed():
    result = TestResult.of(
        "python",
        total=2,
        passed=1,
        failed=1,
        skipped=0,
        duration_ms=1500,
        failures=[TestFailure("test_add", "test_math.py", 12, "assert 1 == 2")],
    )
    shown = presentation.test_presentation("Run Python tests", result)
    assert shown.summary == "1 passed, 1 failed in 1.5 s"
    assert shown.content[0].rows[0][1] == "test_math.py:12"


def test_repl_error_is_shown_instead_of_a_value():
    shown = presentation.repl_presentation(
        "Evaluate in Python REPL",
        ReplResult("python", "~/app", "", "", "NameError: x", 12, True),
    )
    assert shown.summary == "evaluation failed"
    assert "NameError" in shown.content[0].text


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
