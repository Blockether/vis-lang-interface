"""Exact JSON and TOML checks, decided by the standard library's own parsers.

`json.loads` and `tomllib.loads` are the parsers the rest of a toolchain reads
these files with, so a verdict here never disagrees with the build. JSON is also
rewritten with `json.dumps`, which is the only formatter the standard library
offers; TOML has no writer, so TOML is checked but never reformatted.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from vis_lang_interface.results import Diagnostic, FormatResult, LintResult

SUFFIXES = (".json", ".toml")
_TOML_POSITION = re.compile(r"at line (\d+), column (\d+)")


def language_of(path):
    """`"json"`, `"toml"`, or None when the suffix is neither."""
    suffix = Path(path).suffix.lower()
    return {".json": "json", ".toml": "toml"}.get(suffix)


def check_source(source, language, path=""):
    """Findings for one document; an empty tuple means it parses.

    Args:
        source: Document text.
        language: `"json"` or `"toml"`.
        path: File the text came from, for the finding.

    Returns:
        A tuple of `Diagnostic`, at most one long.

    Raises:
        ValueError: The language is neither JSON nor TOML.
    """
    if language == "json":
        try:
            json.loads(source)
        except json.JSONDecodeError as exc:
            return (Diagnostic(path, exc.lineno, exc.colno, "error", exc.msg, "json"),)
        return ()
    if language == "toml":
        try:
            tomllib.loads(source)
        except tomllib.TOMLDecodeError as exc:
            line, column = _toml_position(exc)
            return (Diagnostic(path, line, column, "error", str(exc), "toml"),)
        return ()
    raise ValueError(f"unsupported data language: {language!r}")


def check_files(paths):
    """A `LintResult` over JSON and TOML files.

    Args:
        paths: Files to read.

    Returns:
        The result, counting every file it parsed.

    Raises:
        ValueError: A path is not a JSON or TOML file.
        OSError: A file cannot be read.
    """
    findings = []
    files = [Path(path) for path in paths]
    for file in files:
        language = language_of(file)
        if not language:
            raise ValueError(f"not a JSON or TOML file: {file}")
        findings.extend(
            check_source(file.read_text(encoding="utf-8"), language, str(file))
        )
    return LintResult.of("data", findings, len(files))


def format_json(source, *, indent=2):
    """`source` reparsed and printed with `indent` spaces and a final newline.

    Raises:
        ValueError: The source is not valid JSON.
    """
    return json.dumps(json.loads(source), indent=indent, ensure_ascii=False) + "\n"


def format_files(paths, *, indent=2, is_written=False):
    """Reformat JSON files.

    Args:
        paths: JSON files to format.
        indent: Spaces per level.
        is_written: Whether to rewrite the files that change.

    Returns:
        A `FormatResult` listing what changed.

    Raises:
        ValueError: A path is not a JSON file, or a file does not parse.
        OSError: A file cannot be read or written.
    """
    changed, unchanged = [], []
    for path in paths:
        file = Path(path)
        if language_of(file) != "json":
            raise ValueError(f"not a JSON file: {file}")
        source = file.read_text(encoding="utf-8")
        formatted = format_json(source, indent=indent)
        if formatted == source:
            unchanged.append(str(file))
            continue
        changed.append(str(file))
        if is_written:
            file.write_text(formatted, encoding="utf-8")
    return FormatResult("json", tuple(changed), tuple(unchanged), is_written=is_written)


def _toml_position(exc):
    """1-based line and column of a TOML error, from the exception or its text."""
    line = getattr(exc, "lineno", None)
    column = getattr(exc, "colno", None)
    if isinstance(line, int) and isinstance(column, int):
        return line, column
    found = _TOML_POSITION.search(str(exc))
    if found:
        return int(found.group(1)), int(found.group(2))
    return 1, 1
