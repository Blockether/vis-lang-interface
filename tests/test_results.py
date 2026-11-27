"""The contract types keep their own counts honest."""

import pytest

from vis_lang_interface import (
    BuildArtifact,
    BuildResult,
    CoverageGap,
    CoverageResult,
    Diagnostic,
    FileCoverage,
    FormatResult,
    LintResult,
    ReplResult,
    ReplSession,
    SyntaxResult,
    TestFailure,
    TestResult,
)


def test_lint_result_counts_levels():
    result = LintResult.of(
        "clojure",
        [
            Diagnostic(
                "a.clj", 1, 1, "error", "unresolved symbol", "unresolved-symbol"
            ),
            Diagnostic("a.clj", 4, 2, "warning", "unused binding"),
        ],
        files=1,
    )
    assert (result.errors, result.warnings, result.files) == (1, 1, 1)
    assert result.is_clean is False


def test_clean_lint_result_has_no_findings():
    result = LintResult.of("python", [], files=3)
    assert result.is_clean is True
    assert result.diagnostics == ()


def test_diagnostic_rejects_an_unknown_level():
    with pytest.raises(ValueError, match="level must be"):
        Diagnostic("a.py", 1, 1, "fatal", "boom")


def test_test_result_passes_only_without_failures():
    passing = TestResult.of(
        "python", total=3, passed=3, failed=0, skipped=0, duration_ms=120
    )
    failing = TestResult.of(
        "python",
        total=3,
        passed=2,
        failed=1,
        skipped=0,
        duration_ms=120,
        failures=[TestFailure("test_add", "test_math.py", 12, "assert 1 == 2")],
    )
    assert passing.is_passed is True
    assert failing.is_passed is False
    assert failing.failures[0].test == "test_add"


def test_build_result_counts_its_findings():
    result = BuildResult.of(
        "python",
        "wheel",
        artifacts=[BuildArtifact("dist/app-1.0.0-py3-none-any.whl", "wheel", 4200)],
        diagnostics=[Diagnostic("pyproject.toml", 0, 0, "warning", "deprecated field")],
        duration_ms=900,
    )
    assert (result.errors, result.warnings) == (0, 1)
    assert result.is_built is True
    assert result.artifacts[0].kind == "wheel"


def test_build_with_an_error_is_never_built():
    result = BuildResult.of(
        "clojure",
        "uberjar",
        diagnostics=[Diagnostic("src/app.clj", 12, 3, "error", "Syntax error")],
        duration_ms=300,
    )
    assert result.is_built is False
    assert result.errors == 1


def test_failed_build_keeps_no_artifacts():
    result = BuildResult.of("python", "sdist", duration_ms=10, is_built=False)
    assert result.is_built is False
    assert result.artifacts == ()


def test_syntax_result_is_clean_only_without_diagnostics():
    clean = SyntaxResult.of("clojure", [], files=4)
    broken = SyntaxResult.of(
        "clojure",
        [Diagnostic("src/a.clj", 3, 7, "error", "Unmatched delimiter: )")],
        files=4,
    )
    assert (clean.is_clean, clean.files, clean.diagnostics) == (True, 4, ())
    assert broken.is_clean is False
    assert broken.diagnostics[0].path == "src/a.clj"


def test_coverage_result_sums_files_and_branches_least_covered_first():
    result = CoverageResult.of(
        "python",
        "lines",
        [
            FileCoverage("app/a.py", 9, 10, 3, 4),
            FileCoverage("app/b.py", 1, 4, 0, 2, (CoverageGap(2, 4, "line", "x = 1"),)),
            FileCoverage("app/c.py", 0, 0),
        ],
        report="coverage.json",
    )
    assert (result.covered, result.total, result.percent) == (10, 14, 71.4)
    assert (result.branches_covered, result.branches_total, result.branch_percent) == (
        3,
        6,
        50.0,
    )
    assert [f.path for f in result.files] == ["app/c.py", "app/b.py", "app/a.py"]
    assert result.files[1].percent == 25.0 and result.files[1].branch_percent == 0.0
    assert result.files[0].branch_percent is None
    assert result.files[1].gaps[0].kind == "line"


def test_coverage_result_without_files_measures_nothing():
    result = CoverageResult.of("clojure", "expressions", [])
    assert (result.total, result.percent, result.branch_percent, result.files) == (
        0,
        0.0,
        None,
        (),
    )


def test_a_test_run_carries_its_coverage_only_when_asked():
    plain = TestResult.of(
        "python", total=1, passed=1, failed=0, skipped=0, duration_ms=1
    )
    measured = CoverageResult.of("python", "lines", [FileCoverage("a.py", 1, 2)])
    covered = TestResult.of(
        "python",
        total=1,
        passed=1,
        failed=0,
        skipped=0,
        duration_ms=1,
        coverage=measured,
    )
    assert plain.coverage is None and covered.coverage is measured and covered.is_passed


def test_printed_format_result_gives_a_long_source_only_as_its_size():
    source = "x = 1\n" * 400
    result = FormatResult("python", (), (), source=source)
    assert "x = 1" not in repr(result)
    assert f"source=<{len(source)} chars; read .source>" in repr(result)
    assert result.source == source
    assert "source='y = 2\\n'" in repr(FormatResult("python", (), (), source="y = 2\n"))


def test_printed_result_names_its_command_only_when_detection_picked_it():
    command = ("oxlint", "-f", "json", "src/a.ts")
    configured = LintResult.of("javascript", [], command=command, chosen_by="project")
    guessed = LintResult.of(
        "javascript", [], command=command, chosen_by="preset:oxlint"
    )
    assert configured.command == command
    assert "command" not in repr(configured) and "chosen_by" not in repr(configured)
    assert "chosen_by='preset:oxlint'" in repr(guessed)
    assert repr(command) in repr(guessed)
    formatted = FormatResult(
        "javascript", (), (), command=("prettier",), chosen_by="preset:prettier"
    )
    assert "command=('prettier',)" in repr(formatted)
    assert "command" not in repr(FormatResult("javascript", (), ()))


def test_printed_passed_run_gives_its_output_only_as_its_size():
    output = "tests/test_a.py ....\n" * 200
    result = TestResult.of(
        "python", total=4, passed=4, failed=0, skipped=0, duration_ms=9, output=output
    )
    assert "test_a.py" not in repr(result)
    assert f"output=<{len(output)} chars; read .output>" in repr(result)
    assert result.output == output


def test_printed_failed_run_without_a_parsed_failure_shows_the_output_tail():
    output = "collecting ...\n" * 300 + "ImportError: no module named app"
    result = TestResult.of(
        "python", total=0, passed=0, failed=1, skipped=0, duration_ms=9, output=output
    )
    assert "ImportError: no module named app" in repr(result)
    assert len(repr(result)) < len(output)


def test_lint_print_groups_matching_findings_without_losing_locations():
    rows = [
        Diagnostic("src/a.py", 3, 1, "error", "sort imports", "I001"),
        Diagnostic("src/b.py", 6, 2, "error", "sort imports", "I001"),
        Diagnostic("src/b.py", 10, 1, "error", "unused `sys`", "F401"),
        Diagnostic("src/b.py", 11, 1, "error", "unused `re`", "F401"),
    ]
    result = LintResult.of("python", rows, files=2)
    message = str(result)
    assert str(rows[0]) == "src/a.py:3:1 error I001 sort imports"
    assert "4 errors" in message and "I001 ×2" in message
    assert "src/a.py:3:1, src/b.py:6:2" in message
    assert message.count("sort imports") == 1
    assert "unused `sys`" in message and "unused `re`" in message
    crowded = LintResult.of("python", rows * 200, files=2)
    assert "800 errors" in str(crowded) and "read .diagnostics" in str(crowded)


def test_failed_run_print_preserves_the_exception_inside_a_long_failure():
    output = "raw runner output " * 200
    failure = TestFailure(
        "test_probe",
        "test_probe.py",
        6,
        "assert snapshot == current\n"
        + "  context\n" * 70
        + "E   FileExistsError: directory already exists\n"
        + "  context\n" * 70,
    )
    result = TestResult.of(
        "python",
        total=2,
        passed=1,
        failed=1,
        skipped=0,
        duration_ms=22,
        failures=[failure],
        output=output,
    )
    assert "test_probe.py:6" in str(failure)
    assert "FileExistsError: directory already exists" in str(failure)
    assert "read .message" in str(failure)
    message = str(result)
    assert "1/2 passed, 1 failed" in message
    assert "FileExistsError: directory already exists" in message
    assert "read .failures[0].message" in message and "read .output" in message
    assert "raw runner output" not in message
    assert result.failures[0].message == failure.message and result.output == output


def test_failed_run_print_bounds_the_number_of_failures():
    failures = [TestFailure(f"test_{i}", "t.py", i + 1, "boom") for i in range(40)]
    result = TestResult.of(
        "python",
        total=40,
        passed=0,
        failed=40,
        skipped=0,
        duration_ms=5,
        failures=failures,
    )
    message = str(result)
    assert "test_4 " in message and "test_5 " not in message
    assert "35 more failures; read .failures" in message


def test_failed_run_without_a_parsed_failure_prints_the_runner_tail():
    output = "collecting ...\n" * 300 + "ImportError: no module named app"
    result = TestResult.of(
        "python", total=0, passed=0, failed=1, skipped=0, duration_ms=9, output=output
    )
    assert "ImportError: no module named app" in str(result)
    assert "read .output" in str(result)


def test_repl_session_print_keeps_the_installer_failure_but_not_the_command():
    detail = "dependency installation FAILED\n" + "build log\n" * 400
    session = ReplSession("python", "/app", "/app", ("python", "-i"), True, detail)
    message = str(session)
    assert message.startswith("python REPL running")
    assert "dependency installation FAILED" in message and "read .detail" in message
    assert len(message) < 700 and "/app" not in message and "-i" not in message
    assert session.detail == detail
    # A bounded installer summary with its log path must print whole.
    short = (
        "dependency installation FAILED\n" + "x" * 500 + "\nInstaller log: /tmp/i.log"
    )
    assert str(ReplSession("python", "/app", "/app", (), True, short)).endswith(short)


def test_repl_result_print_keeps_findings_but_not_the_submitted_code():
    result = ReplResult(
        "python",
        "/app",
        "42",
        "scan\n" * 200,
        "RuntimeError: stopped",
        12,
        True,
        code="do_not_echo()",
        repairs=("closed a parenthesis",),
    )
    message = str(result)
    assert message.startswith("python REPL error")
    assert "RuntimeError: stopped" in message and "closed a parenthesis" in message
    assert "42" in message and "scan" in message and "read .output" in message
    assert "do_not_echo" not in message and "do_not_echo" in repr(result)
    assert "not running" in str(ReplResult("python", "/app", "", "", "", 0, False))


def test_format_print_distinguishes_check_write_and_source():
    path = "/app/filter.py"
    check = FormatResult("python", (path,), (), lines_added=87, lines_removed=24)
    written = FormatResult(
        "python",
        (path,),
        (),
        is_written=True,
        chosen_by="preset:ruff",
        command=("ruff", "format"),
    )
    source = FormatResult("python", (), (), source="x = 1\n" * 400)
    assert "would reformat" in str(check) and "+87/-24" in str(check)
    assert path in str(check)
    assert "reformatted" in str(written) and "ruff" in str(written)
    assert "'ruff', 'format'" not in str(written)
    assert "formatted source" in str(source) and "read .source" in str(source)
