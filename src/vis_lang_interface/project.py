"""Finding the project a tool should run in, and the files it should read."""

from __future__ import annotations

import os
from collections.abc import Iterable
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


def string_list(value):
    """`value` as a tuple of strings, where one bare string or path is one entry.

    A parameter typed as a list of strings also accepts a bare string, because a
    string is a sequence of its characters. `tuple("/src/app.py")` named one path
    for each character. Its first one, `/`, made a lint walk the whole
    filesystem (Blockether/vis#324).

    Args:
        value: A string, a path, an iterable of them, or None.

    Returns:
        A tuple of strings. None gives an empty tuple.

    Raises:
        TypeError: `value` or one of its entries is not a string or a path.
    """
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        return (_string(value),)
    if isinstance(value, (bytes, bytearray)) or not isinstance(value, Iterable):
        raise TypeError(
            f"expected a string or a list of strings, got {type(value).__name__}"
        )
    return tuple(_string(one) for one in value)


def _string(one):
    """One entry of a string list, as text."""
    if isinstance(one, str):
        return one
    if isinstance(one, os.PathLike):
        named = os.fspath(one)
        if isinstance(named, str):
            return named
    raise TypeError(f"expected a string or a path, got {type(one).__name__}")


def source_files(paths, suffixes, *, limit=5000):
    """Every file under `paths` with one of `suffixes`, skipping build output.

    The walk skips ignored directories without entering them, and it stops at
    `limit`. So a broad directory gives a bounded answer, not a walk without end.

    Args:
        paths: Files or directories to walk. One bare string is one path.
        suffixes: Extensions to keep, each including its dot.
        limit: Most files to return.

    Returns:
        Sorted absolute paths.

    Raises:
        FileNotFoundError: One of the paths does not exist.
        ValueError: One of the paths is the filesystem root.
        TypeError: `paths` is not a string, a path or a list of them.
    """
    wanted = tuple(suffixes)
    found = set()
    for entry in string_list(paths):
        start = Path(entry).expanduser().resolve(strict=True)
        if start.is_file():
            found.add(start)
            continue
        if start == Path(start.anchor):
            raise ValueError(
                f"refusing to search the filesystem root {start};"
                " name a project directory or its files"
            )
        for directory, children, names in os.walk(start):
            children[:] = sorted(
                name for name in children if name not in IGNORED_DIRECTORIES
            )
            for name in sorted(names):
                if len(found) >= limit:
                    return tuple(sorted(found))
                candidate = Path(directory) / name
                if candidate.suffix in wanted and candidate.is_file():
                    found.add(candidate)
    return tuple(sorted(found)[:limit])
