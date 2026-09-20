"""Finding the project a tool should run in, and the files it should read."""

from __future__ import annotations

from pathlib import Path

IGNORED_DIRECTORIES = frozenset(
    {
        ".cpcache",
        ".git",
        ".gradle",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".shadow-cljs",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)


def project_root(start, markers):
    """The nearest directory at or above `start` holding one of `markers`.

    Args:
        start: File or directory to search from.
        markers: File names that mark a project root, such as `deps.edn`.

    Returns:
        The project directory, or the starting directory when no marker exists.
    """
    here = Path(start).expanduser().resolve()
    if here.is_file():
        here = here.parent
    for directory in [here, *here.parents]:
        if any((directory / marker).exists() for marker in markers):
            return directory
    return here


def source_files(paths, suffixes, *, limit=5000):
    """Every file under `paths` with one of `suffixes`, skipping build output.

    Args:
        paths: Files or directories to walk.
        suffixes: Extensions to keep, each including its dot.
        limit: Most files to return.

    Returns:
        Sorted absolute paths.

    Raises:
        FileNotFoundError: One of the paths does not exist.
    """
    wanted = tuple(suffixes)
    found = []
    for entry in paths:
        start = Path(entry).expanduser().resolve(strict=True)
        if start.is_file():
            found.append(start)
            continue
        for candidate in sorted(start.rglob("*")):
            if len(found) >= limit:
                break
            if candidate.is_file() and candidate.suffix in wanted:
                parts = set(candidate.relative_to(start).parts[:-1])
                if not parts & IGNORED_DIRECTORIES:
                    found.append(candidate)
    return tuple(sorted(set(found))[:limit])
