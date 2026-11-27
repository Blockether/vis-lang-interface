"""What a language tool returns, in shapes that do not depend on the language.

Every field is plain data: a model reads these results and a presentation
renders them without knowing which toolchain produced them. Build them with the
`of` constructors, which derive the counts from the findings so a summary can
never disagree with the list below it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

LEVELS = ("error", "warning", "info")

SHOWN_TEXT = 200
"""Characters of a text field that a printed result shows before it gives only the size."""

SHOWN_TAIL = 1500
"""Characters of runner output that a printed failed run shows when no failure was parsed."""

SHOWN_FAILURES = 5
"""Failures that a printed failed run shows; the others stay in `failures`."""

PRESET = "preset:"
"""The `chosen_by` prefix of a command that detection picked, not the person's configuration."""


def _sized(name, text, limit=SHOWN_TEXT):
    """The repr of a text field, or its size when the text is longer than `limit`."""
    if len(text) <= limit:
        return repr(text)
    return f"<{len(text)} chars; read .{name}>"


def _repr(result, hidden=(), **shown):
    """The dataclass repr of `result`, without the `hidden` fields and with the
    `shown` fields given as ready text."""
    fields = ", ".join(
        f"{name}={shown[name] if name in shown else repr(getattr(result, name))}"
        for name in result.__dataclass_fields__
        if name not in hidden
    )
    return f"{type(result).__name__}({fields})"


def _unguessed(result):
    """The command fields a printed result leaves out: both, unless detection
    picked the command, because only a guess explains a surprising result."""
    return () if result.chosen_by.startswith(PRESET) else ("command", "chosen_by")


def _preview(text, field, limit, *, tail=False):
    """Keep a bounded part of the text and name the full field when cut."""
    if len(text) <= limit:
        return text
    note = f"[… {len(text)} chars; read {field}]"
    if tail:
        return f"{note}\n{text[-limit:].lstrip()}"
    return f"{text[:limit].rstrip()}\n{note}"


def _location(path, line, column=0):
    location = path or "source"
    if line:
        location += f":{line}"
        if column:
            location += f":{column}"
    return location


def _count(count, singular):
    return f"{count} {singular}{'' if count == 1 else 's'}"


def _preset(chosen_by):
    return f" ({chosen_by})" if chosen_by.startswith(PRESET) else ""


_EXCEPTION_LINE = re.compile(
    r"^(?:[\w.$]+\.)?[\w$]*(?:Error|Exception|Failure|Throwable)\b"
)


def _failure_preview(message, field):
    if len(message) <= 500:
        return message
    # Keep the first reason and the last exception line, even inside a traceback.
    lines = (
        line.lstrip().removeprefix("E   ").strip()
        for line in reversed(message.splitlines())
    )
    exception = next((line for line in lines if _EXCEPTION_LINE.match(line)), "")
    if exception and exception in message[:500]:
        return _preview(message, field, 500)
    end = exception[:300] if exception else message[-300:].lstrip()
    reason = message[: 499 - len(end)].rstrip()
    return f"{reason}\n[… {len(message)} chars; read {field}]\n{end}"


@dataclass(frozen=True)
class Diagnostic:
    """One located finding from a linter, compiler or formatter."""

    path: Annotated[str, "File the finding is about; empty for a source string."]
    line: Annotated[int, "1-based line, or 0 when the tool located nothing."]
    column: Annotated[int, "1-based column, or 0 when the tool located nothing."]
    level: Annotated[str, "Severity: error, warning or info."]
    message: Annotated[str, "What the tool reported."]
    rule: Annotated[str, "Rule that fired; empty when the tool names none."] = ""

    def __str__(self):
        location = _location(self.path, self.line, self.column)
        label = f"{self.level} {self.rule}" if self.rule else self.level
        return f"{location} {label} {self.message}".rstrip()

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
    lines_added: Annotated[
        int, "Lines formatting added, over every file or the source string."
    ] = 0
    lines_removed: Annotated[
        int, "Lines formatting removed; a changed line counts as removed and added."
    ] = 0
    command: Annotated[
        tuple[str, ...], "Command that ran, as argv; empty when the tool does not say."
    ] = ()
    chosen_by: Annotated[
        str,
        "Who chose the command: project, global, or preset:<name> when detection picked it.",
    ] = ""

    def __str__(self):
        if self.source:
            status = "formatted source"
        elif self.changed:
            action = "reformatted" if self.is_written else "would reformat"
            status = f"{action} {_count(len(self.changed), 'file')}"
        else:
            status = "no changes"
        if self.unchanged:
            status += f", {len(self.unchanged)} unchanged"
        if self.lines_added or self.lines_removed:
            status += f" +{self.lines_added}/-{self.lines_removed}"
        rows = [f"{self.language}: {status}{_preset(self.chosen_by)}"]
        if self.source:
            rows.append(_preview(self.source, ".source", 500))
        if self.changed:
            rows.append(_preview("\n".join(self.changed), ".changed", 500))
        return "\n".join(rows)

    def __repr__(self):
        """A printed result gives a long formatted text only as its size, and the
        command only when detection picked it."""
        return _repr(self, _unguessed(self), source=_sized("source", self.source))


@dataclass(frozen=True)
class LintResult:
    """Every finding a linter reported, with its own counts."""

    language: Annotated[str, "Language that was linted."]
    files: Annotated[int, "Number of files the linter read."]
    errors: Annotated[int, "Findings at error level."]
    warnings: Annotated[int, "Findings at warning level."]
    diagnostics: Annotated[tuple[Diagnostic, ...], "The findings, in file order."]
    is_clean: Annotated[bool, "Whether the linter reported nothing at all."]
    command: Annotated[
        tuple[str, ...], "Command that ran, as argv; empty when the tool does not say."
    ] = ()
    chosen_by: Annotated[
        str,
        "Who chose the command: project, global, or preset:<name> when detection picked it.",
    ] = ""

    def __str__(self):
        files = _count(self.files, "file")
        heading = f"{self.language} lint{_preset(self.chosen_by)}, {files}"
        if self.is_clean:
            return f"{heading}: clean"
        groups = {}
        for row in self.diagnostics:
            messages = groups.setdefault((row.level, row.rule), {})
            messages.setdefault(row.message, []).append(
                _location(row.path, row.line, row.column)
            )
        infos = len(self.diagnostics) - self.errors - self.warnings
        counts = ", ".join(
            _count(count, label)
            for count, label in (
                (self.errors, "error"),
                (self.warnings, "warning"),
                (infos, "info finding"),
            )
            if count
        )
        rows = []
        for (level, rule), messages in groups.items():
            label = f"{level} {rule}" if rule else level
            count = sum(map(len, messages.values()))
            if count > 1:
                rows.append(f"{label} ×{count}")
            for message, locations in messages.items():
                locations = ", ".join(locations)
                prefix = f"  {locations}" if count > 1 else f"{locations} {label}"
                rows.append(f"{prefix} {message}".rstrip())
        findings = _preview("\n".join(rows), ".diagnostics", 1500)
        return f"{heading}: {counts}\n{findings}"

    def __repr__(self):
        """A printed result gives the command only when detection picked it."""
        return _repr(self, _unguessed(self))

    @classmethod
    def of(cls, language, diagnostics, files=0, *, command=(), chosen_by=""):
        """A result whose counts are derived from `diagnostics`."""
        rows = tuple(diagnostics)
        errors = sum(1 for row in rows if row.level == "error")
        warnings = sum(1 for row in rows if row.level == "warning")
        return cls(
            language,
            int(files),
            errors,
            warnings,
            rows,
            not rows,
            tuple(command),
            str(chosen_by),
        )


@dataclass(frozen=True)
class SyntaxResult:
    """The verdict of the language's own parser: which sources do not parse, and where."""

    language: Annotated[str, "Language whose parser read the sources."]
    files: Annotated[int, "Number of files or source strings the parser read."]
    diagnostics: Annotated[
        tuple[Diagnostic, ...],
        "The first error in each source that does not parse, in file order.",
    ]
    is_clean: Annotated[bool, "Whether every source parsed."]

    @classmethod
    def of(cls, language, diagnostics, files=0):
        """A result that is clean exactly when no source failed to parse."""
        rows = tuple(diagnostics)
        return cls(language, int(files), rows, not rows)


@dataclass(frozen=True)
class TestFailure:
    """One failing test, located where the runner reported it."""

    test: Annotated[
        str, "Test name as the runner spells it, nested names joined with ' › '."
    ]
    path: Annotated[str, "File containing the test; empty when unknown."]
    line: Annotated[int, "1-based line, or 0 when the runner located nothing."]
    message: Annotated[str, "Why it failed: the reason first, its details below."]

    def _summary(self, field):
        test = self.test or "unknown test"
        if self.path or self.line:
            test += f" ({_location(self.path, self.line)})"
        return (
            f"{test}\n{_failure_preview(self.message, field)}" if self.message else test
        )

    def __str__(self):
        return self._summary(".message")


@dataclass(frozen=True)
class CoverageGap:
    """One place in a source file that the tests never ran."""

    line: Annotated[int, "1-based first line, or 0 when the tool located nothing."]
    end_line: Annotated[int, "1-based last line; equal to `line` for one line."]
    kind: Annotated[
        str,
        "`line`, `branch` (a branch of a decision never ran) or `expression`.",
    ]
    detail: Annotated[str, "What never ran, such as the source text or `12 -> 14`."]


@dataclass(frozen=True)
class FileCoverage:
    """How much of one source file the tests ran, and where they did not."""

    path: Annotated[str, "Source file, as the coverage tool names it."]
    covered: Annotated[int, "Measured points that ran: lines, or expressions."]
    total: Annotated[int, "Measured points in the file."]
    branches_covered: Annotated[int, "Branches that ran; 0 without branch data."] = 0
    branches_total: Annotated[int, "Measured branches; 0 without branch data."] = 0
    gaps: Annotated[
        tuple[CoverageGap, ...], "Places that never ran, in line order."
    ] = ()

    @property
    def percent(self) -> float:
        """Covered share in percent; 0 when the file has nothing to measure."""
        return round(100.0 * self.covered / self.total, 1) if self.total else 0.0

    @property
    def branch_percent(self) -> float | None:
        """Covered branch share in percent; None without branch data."""
        if not self.branches_total:
            return None
        return round(100.0 * self.branches_covered / self.branches_total, 1)


@dataclass(frozen=True)
class CoverageResult:
    """The coverage of one instrumented test run."""

    language: Annotated[str, "Language whose tests ran."]
    unit: Annotated[str, "What the tool counts: lines, or expressions."]
    covered: Annotated[int, "Measured points that ran, over all files."]
    total: Annotated[int, "Measured points over all files."]
    files: Annotated[tuple[FileCoverage, ...], "Measured files, least covered first."]
    report: Annotated[str, "Report file the run wrote, for other tools to read."] = ""
    branches_covered: Annotated[int, "Branches that ran, over all files."] = 0
    branches_total: Annotated[int, "Measured branches over all files."] = 0

    @property
    def percent(self) -> float:
        """Covered share in percent; 0 when nothing was measured."""
        return round(100.0 * self.covered / self.total, 1) if self.total else 0.0

    @property
    def branch_percent(self) -> float | None:
        """Covered branch share in percent; None without branch data."""
        if not self.branches_total:
            return None
        return round(100.0 * self.branches_covered / self.branches_total, 1)

    @classmethod
    def of(cls, language, unit, files, *, report=""):
        """A result whose totals are the sums of `files`, least covered first."""
        files = tuple(sorted(files, key=lambda f: (f.percent, -f.total, f.path)))
        return cls(
            language,
            unit,
            sum(int(f.covered) for f in files),
            sum(int(f.total) for f in files),
            files,
            str(report),
            sum(int(f.branches_covered) for f in files),
            sum(int(f.branches_total) for f in files),
        )


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
    coverage: Annotated[
        CoverageResult | None, "Coverage of the run; None unless it was asked for."
    ] = None

    def __str__(self):
        if not self.is_passed:
            verdict = "failed"
        elif not self.total:
            verdict = "no tests ran"
        else:
            verdict = "passed"
        counts = f"{self.passed}/{self.total} passed"
        if self.failed:
            counts += f", {self.failed} failed"
        if self.skipped:
            counts += f", {self.skipped} skipped"
        rows = [f"{self.language} tests {verdict}: {counts} ({self.duration_ms} ms)"]
        for i, failure in enumerate(self.failures[:SHOWN_FAILURES]):
            rows.append(failure._summary(f".failures[{i}].message"))
        if len(self.failures) > SHOWN_FAILURES:
            more = len(self.failures) - SHOWN_FAILURES
            rows.append(f"[… {more} more failures; read .failures]")
        if self.output:
            if self.failures or (self.is_passed and self.total):
                rows.append(f"Runner output: {len(self.output)} chars; read .output")
            else:
                rows.append(_preview(self.output, ".output", SHOWN_TAIL, tail=True))
        if self.coverage is not None:
            rows.append(f"Coverage: {self.coverage.percent}% (read .coverage)")
        return "\n".join(rows)

    def __repr__(self):
        """A printed result gives the runner output only as its size.

        A run that failed, or ran nothing, without a parsed failure shows the
        tail of the output, because the output is then the only cause.
        """
        if self.failures or (self.is_passed and self.total):
            return _repr(self, output=_sized("output", self.output))
        tail = self.output[-SHOWN_TAIL:]
        shown = (
            repr(tail)
            if tail == self.output
            else f"<{len(self.output)} chars; tail: {tail!r}>"
        )
        return _repr(self, output=shown)

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
        coverage=None,
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
            coverage,
        )


@dataclass(frozen=True)
class BuildArtifact:
    """One file a build produced."""

    path: Annotated[str, "Path of the file the build wrote."]
    kind: Annotated[str, "What it is: wheel, sdist, jar, uberjar, binary or archive."]
    size_bytes: Annotated[int, "Size of the file in bytes, or 0 when unknown."] = 0


@dataclass(frozen=True)
class BuildResult:
    """What a build produced, and what the toolchain reported while producing it."""

    language: Annotated[str, "Language that was built."]
    target: Annotated[str, "What was built, as the toolchain names it: wheel, uberjar."]
    artifacts: Annotated[tuple[BuildArtifact, ...], "Files the build wrote."]
    diagnostics: Annotated[tuple[Diagnostic, ...], "Findings the build reported."]
    errors: Annotated[int, "Findings at error level."]
    warnings: Annotated[int, "Findings at warning level."]
    duration_ms: Annotated[int, "Wall time of the build in milliseconds."]
    output: Annotated[str, "Tail of the toolchain's own output."] = ""
    is_built: Annotated[bool, "Whether the build finished without an error."] = False

    @classmethod
    def of(
        cls,
        language,
        target,
        *,
        artifacts=(),
        diagnostics=(),
        duration_ms=0,
        output="",
        is_built=True,
    ):
        """A result whose counts are derived from `diagnostics`.

        A build that reported an error is never built, whatever `is_built` says,
        so a green summary can never sit above an error in the list.
        """
        rows = tuple(diagnostics)
        errors = sum(1 for row in rows if row.level == "error")
        warnings = sum(1 for row in rows if row.level == "warning")
        return cls(
            language,
            target,
            tuple(artifacts),
            rows,
            errors,
            warnings,
            int(duration_ms),
            output,
            bool(is_built) and errors == 0,
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
    code: Annotated[str, "The evaluated code, pretty-printed when it parses."] = ""
    repairs: Annotated[
        tuple[str, ...],
        "Structural repairs made to the code before it was evaluated, one note each.",
    ] = ()

    def __str__(self):
        state = "error" if self.error else "ok" if self.is_running else "not running"
        if self.error and not self.is_running:
            state += ", not running"
        rows = [f"{self.language} REPL {state} ({self.duration_ms} ms)"]
        for field in ("error", "value", "output", "repairs"):
            value = getattr(self, field)
            if value:
                if field == "repairs":
                    value = "; ".join(value)
                rows.append(f"{field}: {_preview(value, f'.{field}', 500)}")
        return "\n".join(rows)


@dataclass(frozen=True)
class ReplSession:
    """A managed REPL process, started or stopped."""

    language: Annotated[str, "Language of the REPL."]
    id: Annotated[str, "Stable id of the REPL, usually its project directory."]
    directory: Annotated[str, "Directory the REPL runs in."]
    command: Annotated[tuple[str, ...], "Command that launched it."]
    is_running: Annotated[bool, "Whether the process is alive now."]
    detail: Annotated[str, "What happened, for the transcript."] = ""

    def __str__(self):
        state = "running" if self.is_running else "not running"
        heading = f"{self.language} REPL {state}"
        if self.detail:
            return f"{heading}\n{_preview(self.detail, '.detail', 600)}"
        return heading
