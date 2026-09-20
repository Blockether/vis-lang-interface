"""The contract types keep their own counts honest."""

import pytest

from vis_lang_interface import Diagnostic, LintResult, TestFailure, TestResult


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
