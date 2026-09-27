"""How language results appear in the activity view.

Every language extension shows the same thing for the same kind of work: a
capitalized headline naming the task, a summary a reader can act on, and the
findings themselves, grouped where a reader looks for them: lint findings by
directory, a test run by failing test. Nothing below a summary repeats it.
Build a render callback with `renderer` and hand it to `vis.Activity`.
"""

from __future__ import annotations

import posixpath
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


def _clip(text, limit=MAX_TEXT):
    """`text` shortened to `limit` characters, marked when anything was dropped."""
    body = text.strip()
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


def format_presentation(label, result):
    """Presentation for a `FormatResult`."""
    changed = len(result.changed)
    if result.source and not changed:
        summary = "already formatted" if not result.changed else "reformatted"
        return vis.ActivityPresentation(
            label, summary, (vis.ActivityCode(_clip(result.source), result.language),)
        )
    if not changed:
        summary = f"{_files(len(result.unchanged))} already formatted"
        return vis.ActivityPresentation(label, summary)
    verb = "rewritten" if result.is_written else "to reformat"
    summary = f"{_files(changed)} {verb}"
    rows = tuple(vis.ActivityText(path) for path in result.changed[:MAX_ROWS])
    return vis.ActivityPresentation(label, summary, rows)


def _findings(rows, directory=""):
    """`rows` as a findings table; within `directory` a file is named alone."""
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
    """One failing test: where and why on one line, the whole message behind it."""
    message = failure.message.strip()
    lines = message.splitlines()
    reason = lines[0] if lines else ""
    said = " · ".join(
        part for part in (_location(failure.path, failure.line), reason) if part
    )
    summary = _line(said)
    is_whole = len(lines) <= 1 and summary == _flat(said)
    content = () if is_whole else (vis.ActivityCode(_clip(message)),)
    headline = _line(failure.test) or _line(failure.path) or "Unnamed test"
    return vis.ActivitySection(headline, summary or "no message", content)


def test_presentation(label, result):
    """Presentation for a `TestResult`, one section per failing test.

    A passing run's own output only repeats its counts, so the output appears
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


def repl_presentation(label, result):
    """Presentation for a `ReplResult`."""
    if result.error:
        return vis.ActivityPresentation(
            label, "evaluation failed", (vis.ActivityText(_clip(result.error)),)
        )
    summary = f"{result.duration_ms} ms"
    content = []
    if result.output:
        content.append(vis.ActivityText(_clip(result.output)))
    if result.value:
        content.append(vis.ActivityCode(_clip(result.value), result.language))
    return vis.ActivityPresentation(label, summary, tuple(content))


def session_presentation(label, session):
    """Presentation for a `ReplSession`: the REPL and what happened, on one line.

    The detail already says what happened, so it is the summary rather than a
    preview repeating it; a session without one reads as its state.
    """
    happened = session.detail or ("running" if session.is_running else "not running")
    return vis.ActivityPresentation(label, _line(f"{session.id} · {happened}"))


def renderer(label, build):
    """A render callback showing `build(result)`, or the error when one is raised.

    Args:
        label: Headline for the binding, in capitalized English.
        build: Function turning the result into an `ActivityPresentation`.

    Returns:
        A callback for `vis.Activity(render=...)`.
    """

    def render(*, phase, result=None, error=None, **_):
        if phase == "success" and result is not None:
            return build(result)
        if phase == "failure":
            detail = _clip(str(error), 1000) if error else "no detail"
            return vis.ActivityPresentation(
                label, "failed", (vis.ActivityText(detail),)
            )
        return None

    return render


def activity(label, build, *, show_start=True):
    """A complete `vis.Activity` for a language binding."""
    return vis.Activity(
        label=label, render=renderer(label, build), show_start=show_start
    )
