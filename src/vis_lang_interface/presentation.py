"""How language results appear in the activity view.

Every language extension shows the same thing for the same kind of work. It
shows a capitalized headline that names the task and a summary that a reader can
act on. It also shows the findings, grouped where a reader looks for them. Lint
findings are grouped by directory, and a test run by failing test. Nothing below
a summary repeats it. Build a render callback with `renderer` and give it to
`vis.Activity`.
"""

from __future__ import annotations

import posixpath
import textwrap
from dataclasses import fields

import blockether.vis.extension as vis

from vis_lang_interface.results import LEVELS

MAX_ROWS = 20
MAX_TEXT = 4000
# A directory's findings and a run's failing tests each wait behind their own
# disclosure; these bounds only stop a pathological run, and a cut is labelled.
MAX_FINDINGS = 100
MAX_SECTIONS = 50
MAX_LINE = 200

# Vis hosts that predate check verdicts refuse the keyword; the summary reports alone.
_REPORTS_VERDICT = "verdict" in {
    field.name for field in fields(vis.ActivityPresentation)
}


def _files(count):
    """`count` as "1 file" or "7 files"."""
    return f"{count} file" if count == 1 else f"{count} files"


def _artifacts(count):
    """`count` as "1 artifact" or "3 artifacts"."""
    return f"{count} artifact" if count == 1 else f"{count} artifacts"


def _size(count):
    """`count` bytes as a short, readable size."""
    if count < 1000:
        return f"{count} B"
    if count < 1000 * 1000:
        return f"{count / 1000:.1f} kB"
    return f"{count / 1000 / 1000:.1f} MB"


def _duration(ms):
    """`ms` milliseconds as "12 ms" or "1.5 s"."""
    if ms < 1000:
        return f"{ms} ms"
    return f"{ms / 1000:.1f} s"


def _clip(text, limit=MAX_TEXT):
    """`text` without surrounding blank lines, cut at `limit` characters and marked.

    Indentation of the first line stays, so pretty-printed code keeps its shape.
    """
    lines = text.rstrip().splitlines()
    start = next((n for n, line in enumerate(lines) if line.strip()), len(lines))
    body = "\n".join(lines[start:])
    if len(body) <= limit:
        return body
    return body[:limit] + "\n… truncated"


def _count(count, noun):
    """`count` with its noun, as "1 error", "2 errors" or "2 info"."""
    if count == 1 or noun == "info":
        return f"{count} {noun}"
    return f"{count} {noun}s"


def _tally(rows):
    """Non-zero finding counts of `rows` by level, as "2 errors, 1 warning"."""
    counts = {level: sum(1 for row in rows if row.level == level) for level in LEVELS}
    return ", ".join(_count(count, level) for level, count in counts.items() if count)


def _flat(text):
    """`text` on one line: control characters and whitespace runs become one space."""
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())


def _line(text, limit=MAX_LINE):
    """`text` as one line a headline or summary can carry, marked when cut."""
    line = _flat(text)
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    if len(line.encode("utf-8")) > 512:
        line = line.encode("utf-8")[:509].decode("utf-8", "ignore") + "…"
    return line


def _tail(text, limit=MAX_LINE):
    """`text` as one line that keeps its end, marked at the front when cut.

    A nested test name ends with its own case, which sets it apart from its
    siblings. So a long name loses its outer descriptions first.
    """
    line = _flat(text)
    if len(line) > limit:
        line = "…" + line[len(line) - limit + 1 :].lstrip()
    data = line.encode("utf-8")
    if len(data) > 512:
        line = "…" + data[-509:].decode("utf-8", "ignore")
    return line


def _location(path, line):
    """`path:line`, or whichever of the two is known."""
    if path and line:
        return f"{path}:{line}"
    return path or (str(line) if line else "")


def _checks(label, summary, content, sections=(), *, is_passed):
    """A check's presentation, carrying its verdict to Vis hosts that read one."""
    if not _REPORTS_VERDICT:
        return vis.ActivityPresentation(label, summary, content, sections)
    verdict = "passed" if is_passed else "failed"
    return vis.ActivityPresentation(label, summary, content, sections, verdict=verdict)


def _line_changes(result):
    """The lines formatting changed, as "+14 −9 lines", or empty when none were counted."""
    if not (result.lines_added or result.lines_removed):
        return ""
    return f"+{result.lines_added} −{result.lines_removed} lines"


def format_presentation(label, result):
    """Presentation for a `FormatResult`: how much formatting changed, in its summary.

    A reader wants to know whether formatting touched anything and how much, so
    the summary counts files and changed lines. The formatted text and the file
    list stay in the result that a model reads. The activity repeats neither.
    """
    lines = _line_changes(result)
    counted = f" ({lines})" if lines else ""
    changed = len(result.changed)
    files = changed + len(result.unchanged)
    if not files:
        if lines:
            return vis.ActivityPresentation(label, f"reformatted{counted}")
        said = "already formatted" if result.source else "nothing to format"
        return vis.ActivityPresentation(label, said)
    if not changed:
        return vis.ActivityPresentation(label, f"{_files(files)} already formatted")
    where = f"{changed} of {_files(files)}" if files > changed else _files(changed)
    if result.is_written:
        verb = "reformatted"
    else:
        verb = "needs formatting" if changed == 1 else "need formatting"
    return vis.ActivityPresentation(label, f"{where} {verb}{counted}")


def _findings(rows, directory=""):
    """`rows` as a findings table. Within `directory`, a file is named alone."""
    shown = rows[:MAX_FINDINGS]
    table = vis.ActivityTable(
        ("Location", "Level", "Rule", "Message"),
        tuple(
            (
                _location(
                    posixpath.basename(row.path) if directory else row.path, row.line
                ),
                row.level,
                row.rule,
                row.message,
            )
            for row in shown
        ),
    )
    if len(shown) == len(rows):
        return (table,)
    note = f"Showing the first {len(shown)} of {len(rows)} findings."
    return (table, vis.ActivityText(note))


def _directory_section(directory, rows):
    """One directory's findings, with its own counts in the summary."""
    files = sorted({row.path for row in rows})
    where = posixpath.basename(files[0]) if len(files) == 1 else _files(len(files))
    return vis.ActivitySection(
        _line(directory),
        _line(f"{_tally(rows)} in {where}"),
        _findings(rows, directory),
    )


def lint_presentation(label, result):
    """Presentation for a `LintResult`, its findings grouped by directory.

    Each directory is a section whose summary carries its own counts, so a reader
    sees where the findings are before opening any of them. Findings in a single
    directory need no grouping and form one table.
    """
    if result.is_clean:
        checked = f" in {_files(result.files)}" if result.files else ""
        return _checks(label, f"no findings{checked}", (), is_passed=True)
    rows = result.diagnostics
    flagged = len({row.path for row in rows})
    where = (
        f"{flagged} of {_files(result.files)}"
        if result.files > flagged
        else _files(flagged)
    )
    summary = f"{_tally(rows)} in {where}"
    groups = {}
    for row in rows:
        groups.setdefault(posixpath.dirname(row.path) or ".", []).append(row)
    if len(groups) == 1:
        return _checks(label, summary, _findings(rows), is_passed=False)
    directories = sorted(groups)
    sections = tuple(
        _directory_section(directory, groups[directory])
        for directory in directories[:MAX_SECTIONS]
    )
    content = ()
    if len(directories) > MAX_SECTIONS:
        note = f"Showing the first {MAX_SECTIONS} of {len(directories)} directories."
        content = (vis.ActivityText(note),)
    return _checks(label, summary, content, sections, is_passed=False)


def syntax_presentation(label, result):
    """Presentation for a `SyntaxResult`: the sources that do not parse, by directory.

    Each source that does not parse shows the first error its parser reported,
    grouped like lint findings. A clean verdict counts the files the parser read.
    """
    if result.is_clean:
        checked = f" in {_files(result.files)}" if result.files else ""
        return _checks(label, f"no syntax errors{checked}", (), is_passed=True)
    return lint_presentation(label, result)


def _test_counts(result):
    """The run's non-zero counts, failures first as runners print them."""
    counts = (
        (result.failed, "failed"),
        (result.passed, "passed"),
        (result.skipped, "skipped"),
    )
    said = ", ".join(f"{count} {word}" for count, word in counts if count)
    return said or "no tests ran"


def _failure_section(failure):
    """One failing test: where and why on one line, the details behind it.

    The first line of the message is the reason, and it already sits in the
    summary. So the section holds only what follows it, such as the expected and
    actual values. A reason too long for the summary is shown whole.
    """
    message = textwrap.dedent(failure.message).strip()
    reason, _, details = message.partition("\n")
    said = " · ".join(
        part for part in (_location(failure.path, failure.line), reason.strip()) if part
    )
    summary = _line(said)
    if summary != _flat(said):
        content = (vis.ActivityCode(_clip(message)),)
    elif details.strip():
        content = (vis.ActivityCode(_clip(textwrap.dedent(details))),)
    else:
        content = ()
    headline = _tail(failure.test) or _line(failure.path) or "Unnamed test"
    return vis.ActivitySection(headline, summary or "no message", content)


def test_presentation(label, result):
    """Presentation for a `TestResult`, one section per failing test.

    A passing run's own output only repeats its counts. So the output appears
    only for a failed run that named no failing test, where it is the evidence.
    """
    summary = f"{_test_counts(result)} in {result.duration_ms / 1000:.1f} s"
    shown = result.failures[:MAX_SECTIONS]
    sections = tuple(_failure_section(failure) for failure in shown)
    content = ()
    if len(shown) < len(result.failures):
        note = (
            f"Showing the first {len(shown)} of {len(result.failures)} failing tests."
        )
        content = (vis.ActivityText(note),)
    elif not result.failures and not result.is_passed and result.output:
        content = (vis.ActivityCode(_clip(result.output)),)
    return _checks(label, summary, content, sections, is_passed=result.is_passed)


def build_presentation(label, result):
    """Presentation for a `BuildResult`."""
    seconds = result.duration_ms / 1000
    if not result.is_built:
        summary = f"build failed in {seconds:.1f} s"
    elif result.artifacts:
        summary = f"{_artifacts(len(result.artifacts))} in {seconds:.1f} s"
    else:
        summary = f"nothing to build in {seconds:.1f} s"
    content = []
    if result.artifacts:
        rows = tuple(
            (artifact.path, artifact.kind, _size(artifact.size_bytes))
            for artifact in result.artifacts[:MAX_ROWS]
        )
        content.append(vis.ActivityTable(("Artifact", "Kind", "Size"), rows))
    if result.diagnostics:
        rows = tuple(
            (
                f"{row.path}:{row.line}" if row.path else str(row.line),
                row.level,
                row.message,
            )
            for row in result.diagnostics[:MAX_ROWS]
        )
        content.append(vis.ActivityTable(("Location", "Level", "Message"), rows))
    elif not result.artifacts and result.output:
        content.append(vis.ActivityText(_clip(result.output)))
    return vis.ActivityPresentation(label, summary, tuple(content))


def _block(heading, text, language=None):
    """`text` as code under its `heading`, or nothing when there is no text."""
    if not text.strip():
        return ()
    return (vis.ActivityHeading(heading), vis.ActivityCode(_clip(text), language))


def _repl_summary(result):
    """How an evaluation ended, on one line: error or value, time and repairs."""
    took = _duration(result.duration_ms)
    if result.repairs:
        took += f" after {_count(len(result.repairs), 'repair')}"
    error = result.error.strip()
    value = result.value.strip()
    if error:
        said = f"failed in {took} · {error.splitlines()[0]}"
    elif value and "\n" not in value and len(value) <= 80:
        said = f"returned {value} in {took}"
    elif "\n" in value:
        said = f"returned a {len(value.splitlines())}-line value in {took}"
    elif value:
        said = f"returned a value in {took}"
    else:
        said = f"finished in {took}"
    return _line(said)


def repl_presentation(label, result):
    """Presentation for a `ReplResult`, in the order a reader follows an evaluation.

    The evaluated code comes first, then the repairs made to it before it ran,
    what it printed, its error and its value. Each appears under its own
    heading, and only when there is something to show. Code and value keep the
    pretty-printing that the language extension gave them.
    """
    content = (
        *_block("Code", result.code, result.language),
        *_block("Repairs", "\n".join(result.repairs)),
        *_block("Output", result.output),
        *_block("Error", result.error),
        *_block("Value", result.value, result.language),
    )
    return vis.ActivityPresentation(label, _repl_summary(result), content)


def session_presentation(label, session):
    """Presentation for a `ReplSession`: the REPL and what happened, on one line.

    The detail already says what happened, so it is the summary, not a preview
    that repeats it. A session without a detail reads as its state.
    """
    happened = session.detail or ("running" if session.is_running else "not running")
    return vis.ActivityPresentation(label, _line(f"{session.id} · {happened}"))


def code_argument(language):
    """A `describe` callback showing the `code` argument of an evaluation call.

    Pass it to `activity` for a REPL binding, so the running row and a failed
    call still show the code the evaluation was given.

    Args:
        language: Language the code is written in, for highlighting.
    """

    def describe(args, kwargs):
        code = kwargs.get("code")
        if not isinstance(code, str):
            code = next((arg for arg in args if isinstance(arg, str)), "")
        return _block("Code", code, language)

    return describe


def renderer(label, build, *, describe=None):
    """A render callback showing `build(result)`, or the error when one is raised.

    Args:
        label: Headline for the binding, in capitalized English.
        build: Function turning the result into an `ActivityPresentation`.
        describe: Optional function of the call's `args` and `kwargs`. It
            returns blocks that show what the call was given. They appear while
            the call runs, and above the error when it fails.

    Returns:
        A callback for `vis.Activity(render=...)`.
    """

    def given(args, kwargs):
        if describe is None:
            return ()
        return tuple(describe(tuple(args or ()), dict(kwargs or {})))

    def render(*, phase, args=(), kwargs=None, result=None, error=None, **_):
        if phase == "success" and result is not None:
            return build(result)
        if phase == "failure":
            detail = _clip(str(error), 1000) if error else "no detail"
            content = given(args, kwargs)
            if content:
                content += (vis.ActivityHeading("Error"), vis.ActivityCode(detail))
            else:
                content = (vis.ActivityText(detail),)
            return vis.ActivityPresentation(label, "failed", content)
        if phase == "start":
            content = given(args, kwargs)
            if content:
                return vis.ActivityPresentation(label, "running", content)
        return None

    return render


def activity(label, build, *, show_start=True, describe=None):
    """A complete `vis.Activity` for a language binding. See `renderer`."""
    return vis.Activity(
        label=label,
        render=renderer(label, build, describe=describe),
        show_start=show_start,
    )
