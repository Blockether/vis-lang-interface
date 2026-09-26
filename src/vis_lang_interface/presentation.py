"""How language results appear in the activity view.

Every language extension shows the same thing for the same kind of work: a
capitalized headline naming the task, a summary a reader can act on, and the
findings themselves. Build a render callback with `renderer` and hand it to
`vis.Activity`.
"""

from __future__ import annotations

from dataclasses import fields

import blockether.vis.extension as vis

MAX_ROWS = 20
MAX_TEXT = 4000

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


def _checks(label, summary, content, *, is_passed):
    """A check's presentation, carrying its verdict to Vis hosts that read one."""
    if not _REPORTS_VERDICT:
        return vis.ActivityPresentation(label, summary, content)
    verdict = "passed" if is_passed else "failed"
    return vis.ActivityPresentation(label, summary, content, verdict=verdict)


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


def lint_presentation(label, result):
    """Presentation for a `LintResult`."""
    if result.is_clean:
        summary = f"no findings in {_files(result.files)}"
        return _checks(label, summary, (), is_passed=True)
    summary = (
        f"{result.errors} errors, {result.warnings} warnings in {_files(result.files)}"
    )
    rows = tuple(
        (
            f"{row.path}:{row.line}" if row.path else str(row.line),
            row.level,
            row.rule,
            row.message,
        )
        for row in result.diagnostics[:MAX_ROWS]
    )
    table = vis.ActivityTable(("Location", "Level", "Rule", "Message"), rows)
    return _checks(label, summary, (table,), is_passed=False)


def test_presentation(label, result):
    """Presentation for a `TestResult`."""
    seconds = result.duration_ms / 1000
    counts = f"{result.passed} passed, {result.failed} failed"
    if result.skipped:
        counts += f", {result.skipped} skipped"
    summary = f"{counts} in {seconds:.1f} s"
    content = []
    if result.failures:
        rows = tuple(
            (
                failure.test,
                f"{failure.path}:{failure.line}" if failure.path else "",
                failure.message.splitlines()[0] if failure.message else "",
            )
            for failure in result.failures[:MAX_ROWS]
        )
        content.append(vis.ActivityTable(("Test", "Location", "Message"), rows))
    elif result.output:
        content.append(vis.ActivityText(_clip(result.output)))
    return _checks(label, summary, tuple(content), is_passed=result.is_passed)


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
    """Presentation for a `ReplSession`."""
    summary = "running" if session.is_running else "stopped"
    content = (vis.ActivityText(session.detail),) if session.detail else ()
    return vis.ActivityPresentation(label, f"{session.id} {summary}", content)


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
