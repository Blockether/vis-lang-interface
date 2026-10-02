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
    SyntaxResult,
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


def test_syntax_presentation_counts_clean_files_and_shows_each_error():
    clean = presentation.syntax_presentation(
        "Check Clojure syntax", SyntaxResult.of("clojure", [], files=3)
    )
    assert clean.summary == "no syntax errors in 3 files"
    assert clean.content == ()
    broken = presentation.syntax_presentation(
        "Check Clojure syntax",
        SyntaxResult.of(
            "clojure",
            [Diagnostic("src/a.clj", 4, 1, "error", "EOF while reading")],
            files=3,
        ),
    )
    assert broken.summary == "1 error in 1 of 3 files"
    assert broken.content[0].rows[0] == (
        "src/a.clj:4",
        "error",
        "",
        "EOF while reading",
    )


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


def _format(result):
    return presentation.format_presentation("Format Clojure code", result)


def test_format_counts_files_and_lines_without_listing_them():
    shown = _format(
        FormatResult(
            "clojure",
            ("a.clj",),
            ("b.clj", "c.clj"),
            is_written=True,
            lines_added=3,
            lines_removed=1,
        )
    )
    assert shown.summary == "1 of 3 files reformatted (+3 −1 lines)"
    assert (shown.content, shown.sections) == ((), ())


def test_format_check_says_which_files_need_formatting():
    summaries = [
        _format(FormatResult("python", changed, (), lines_added=2, lines_removed=2))
        for changed in (("a.py",), ("a.py", "b.py"))
    ]
    assert [shown.summary for shown in summaries] == [
        "1 file needs formatting (+2 −2 lines)",
        "2 files need formatting (+2 −2 lines)",
    ]


def test_formatted_source_is_counted_not_shown():
    changed = _format(
        FormatResult("clojure", (), (), "(ns a)\n", lines_added=1, lines_removed=2)
    )
    assert (changed.summary, changed.content) == ("reformatted (+1 −2 lines)", ())
    unchanged = _format(FormatResult("clojure", (), (), "(ns a)\n"))
    assert (unchanged.summary, unchanged.content) == ("already formatted", ())


def test_format_without_changes_or_files_says_so():
    summaries = [
        _format(FormatResult("clojure", (), unchanged)).summary
        for unchanged in (("a.clj",), ("a.clj", "b.clj"), ())
    ]
    assert summaries == [
        "1 file already formatted",
        "2 files already formatted",
        "nothing to format",
    ]


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
    assert div.content[0].text == "in divide()"


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


def test_a_long_nested_test_name_keeps_its_own_case():
    name = " › ".join(["an outer description " * 12, "keeps the case that failed"])
    result = TestResult.of(
        "clojure",
        total=1,
        passed=0,
        failed=1,
        skipped=0,
        duration_ms=5,
        failures=[
            TestFailure(name, "a_test.clj", 7, "Expected: (= 1 2)\nActual: false")
        ],
    )
    (section,) = presentation.test_presentation("Run Clojure tests", result).sections
    assert section.headline.startswith("…")
    assert section.headline.endswith("description › keeps the case that failed")
    assert len(section.headline) <= presentation.MAX_LINE
    assert section.summary == "a_test.clj:7 · Expected: (= 1 2)"
    assert [block.text for block in section.content] == ["Actual: false"]


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


def _texts(shown):
    return [block.text for block in shown.content]


def test_an_evaluation_shows_code_output_and_value_in_order():
    shown = presentation.repl_presentation(
        "Evaluate in Clojure REPL",
        ReplResult(
            "clojure",
            "nrepl:~/app",
            "{:a 1,\n :b [1 2 3]}",
            "\n  hello\n",
            "",
            12,
            True,
            code='(do\n  (println "  hello")\n  {:a 1, :b [1 2 3]})',
        ),
    )
    assert shown.summary == "returned a 2-line value in 12 ms"
    assert _texts(shown) == [
        "Code",
        '(do\n  (println "  hello")\n  {:a 1, :b [1 2 3]})',
        "Output",
        "  hello",
        "Value",
        "{:a 1,\n :b [1 2 3]}",
    ]
    code, output, value = shown.content[1::2]
    assert [code.language, output.language, value.language] == [
        "clojure",
        None,
        "clojure",
    ]


def test_a_failed_evaluation_shows_its_code_and_error():
    error = "NameError: name 'x' is not defined"
    shown = presentation.repl_presentation(
        "Evaluate in Python REPL",
        ReplResult("python", "~/app", "", "", error, 12, True, code="x + 1"),
    )
    assert shown.summary == f"failed in 12 ms · {error}"
    assert _texts(shown) == ["Code", "x + 1", "Error", error]


def test_an_evaluation_summary_says_how_it_ended():
    def summary(value, *, error="", is_running=True, duration_ms=3):
        result = ReplResult("clojure", "r", value, "", error, duration_ms, is_running)
        return presentation.repl_presentation("Evaluate", result).summary

    assert summary("42") == "returned 42 in 3 ms"
    assert summary("x" * 81) == "returned a value in 3 ms"
    assert summary("") == "finished in 3 ms"
    assert summary("", duration_ms=1500) == "finished in 1.5 s"
    assert summary("", error="Timed out\nafter 3 ms", is_running=False) == (
        "failed in 3 ms · Timed out"
    )


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


def test_an_evaluation_shows_its_code_while_running_and_when_the_call_fails():
    render = presentation.renderer(
        "Evaluate in Clojure REPL",
        lambda result: presentation.repl_presentation("Evaluate", result),
        describe=presentation.code_argument("clojure"),
    )
    tools = object()
    running = render(phase="start", args=(tools, "(+ 1 2)"), kwargs={})
    assert (running.summary, _texts(running)) == ("running", ["Code", "(+ 1 2)"])
    failed = render(
        phase="failure",
        args=(tools,),
        kwargs={"code": "(+ 1 2)"},
        error=RuntimeError("No REPL is running in ~/app"),
    )
    assert failed.summary == "failed"
    assert _texts(failed) == ["Code", "(+ 1 2)", "Error", "No REPL is running in ~/app"]
    assert render(phase="start", args=(tools,), kwargs={}) is None


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
