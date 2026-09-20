"""What a language tool returns, in shapes that do not depend on the language.

Every field is plain data: a model reads these results and a presentation
renders them without knowing which toolchain produced them. Build them with the
`of` constructors, which derive the counts from the findings so a summary can
never disagree with the list below it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

LEVELS = ("error", "warning", "info")


@dataclass(frozen=True)
class Diagnostic:
    """One located finding from a linter, compiler or formatter."""

    path: Annotated[str, "File the finding is about; empty for a source string."]
    line: Annotated[int, "1-based line, or 0 when the tool located nothing."]
    column: Annotated[int, "1-based column, or 0 when the tool located nothing."]
    level: Annotated[str, "Severity: error, warning or info."]
    message: Annotated[str, "What the tool reported."]
    rule: Annotated[str, "Rule that fired; empty when the tool names none."] = ""

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, not {self.level!r}")


@dataclass(frozen=True)
class FormatResult:
    """What formatting changed."""

    language: Annotated[str, "Language that was formatted."]
    changed: Annotated[tuple[str, ...], "Files whose contents were rewritten."]
    unchanged: Annotated[tuple[str, ...], "Files that were already formatted."]
    source: Annotated[str, "Formatted text when a source string was formatted."] = ""
    is_written: Annotated[bool, "Whether the files on disk were rewritten."] = False


@dataclass(frozen=True)
class LintResult:
    """Every finding a linter reported, with its own counts."""

    language: Annotated[str, "Language that was linted."]
    files: Annotated[int, "Number of files the linter read."]
    errors: Annotated[int, "Findings at error level."]
    warnings: Annotated[int, "Findings at warning level."]
    diagnostics: Annotated[tuple[Diagnostic, ...], "The findings, in file order."]
    is_clean: Annotated[bool, "Whether the linter reported nothing at all."]

    @classmethod
    def of(cls, language, diagnostics, files=0):
        """A result whose counts are derived from `diagnostics`."""
        rows = tuple(diagnostics)
        errors = sum(1 for row in rows if row.level == "error")
        warnings = sum(1 for row in rows if row.level == "warning")
        return cls(language, int(files), errors, warnings, rows, not rows)


@dataclass(frozen=True)
class TestFailure:
    """One failing test, located where the runner reported it."""

    test: Annotated[str, "Test name as the runner spells it."]
    path: Annotated[str, "File containing the test; empty when unknown."]
    line: Annotated[int, "1-based line, or 0 when the runner located nothing."]
    message: Annotated[str, "Why it failed."]


@dataclass(frozen=True)
class TestResult:
    """A test run, counted the way the runner counted it."""

    language: Annotated[str, "Language whose tests ran."]
    total: Annotated[int, "Tests the runner executed."]
    passed: Annotated[int, "Tests that passed."]
    failed: Annotated[int, "Tests that failed or errored."]
    skipped: Annotated[int, "Tests the runner skipped."]
    duration_ms: Annotated[int, "Wall time of the run in milliseconds."]
    failures: Annotated[tuple[TestFailure, ...], "The failing tests."]
    output: Annotated[str, "Tail of the runner's own output."] = ""
    is_passed: Annotated[bool, "Whether the run finished with no failure."] = False

    @classmethod
    def of(
        cls,
        language,
        *,
        total,
        passed,
        failed,
        skipped,
        duration_ms,
        failures=(),
        output="",
    ):
        """A result that passes exactly when nothing failed."""
        return cls(
            language,
            int(total),
            int(passed),
            int(failed),
            int(skipped),
            int(duration_ms),
            tuple(failures),
            output,
            int(failed) == 0,
        )


@dataclass(frozen=True)
class ReplResult:
    """What one evaluation in a live REPL produced."""

    language: Annotated[str, "Language of the REPL."]
    id: Annotated[str, "Stable id of the REPL, usually its project directory."]
    value: Annotated[str, "Printed value of the last expression."]
    output: Annotated[str, "Anything the evaluation printed."]
    error: Annotated[str, "Error text; empty when the evaluation succeeded."]
    duration_ms: Annotated[int, "Wall time of the evaluation in milliseconds."]
    is_running: Annotated[bool, "Whether the REPL is still available."]


@dataclass(frozen=True)
class ReplSession:
    """A managed REPL process, started or stopped."""

    language: Annotated[str, "Language of the REPL."]
    id: Annotated[str, "Stable id of the REPL, usually its project directory."]
    directory: Annotated[str, "Directory the REPL runs in."]
    command: Annotated[tuple[str, ...], "Command that launched it."]
    is_running: Annotated[bool, "Whether the process is alive now."]
    detail: Annotated[str, "What happened, for the transcript."] = ""
