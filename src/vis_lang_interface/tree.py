"""Files under one root, listed once and then kept current by stat calls.

A `Tree` notes the mtime of every directory that it lists. Later it reads again
only a directory whose mtime moved, and it stats each file that it knows. One
check of a large tree so costs stat calls, not a new listing or file reads.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import blockether.vis.extension as vis

from vis_lang_interface import process
from vis_lang_interface.project import IGNORED_DIRECTORIES

# Most directory entries one walk visits where git cannot list the tree.
MOST_ENTRIES = 20_000


class Tree:
    """Files under one root as last seen: listed once, then kept current by stat.

    `seen` maps each file the parser reads to the `(mtime_ns, size)` it had when
    it was listed or last parsed; None marks a file that was never parsed. A
    directory whose own mtime moved gained or lost entries, so only those
    directories are read again.
    """

    def __init__(self, root, files, covers, previous=None):
        # Plain strings and os.path: pathlib made one listing hundreds of ms slower.
        self.root = os.fspath(root)
        self._inside = os.path.join(self.root, "")
        self.listed_at = time.monotonic()
        self.seen = {}
        self.directories = {}
        known = previous.seen if previous else None
        self._note(self.root)
        for path in files:
            path = os.fspath(path)
            self._note_parents(path)
            if covers(path):
                self.seen[path] = stamp_of(path) if known is None else known.get(path)

    def changes(self, covers):
        """`{path: stamp}` for every file the parser reads that changed since seen."""
        for directory, stamp in list(self.directories.items()):
            now = _mtime(directory)
            if now is None:
                del self.directories[directory]
            elif now != stamp:
                self.directories[directory] = now
                self._read(directory, covers)
        changed = {}
        for path, stamp in self.seen.items():
            now = stamp_of(path)
            if now != stamp or stamp is None:
                changed[path] = now
        return changed

    def settle(self, changed):
        """Take `{path: stamp}` from `changes` as seen; a None stamp forgets a gone file."""
        for path, now in changed.items():
            if now is None:
                self.seen.pop(path, None)
            else:
                self.seen[path] = now

    def _read(self, directory, covers):
        """Take in the new entries of one directory; a new directory is walked."""
        try:
            with os.scandir(directory) as entries:
                listed = list(entries)
        except OSError:
            return
        for entry in listed:
            if entry.is_dir(follow_symlinks=False):
                if entry.path not in self.directories and _walkable(entry.name):
                    for path in walked(entry.path, self):
                        if covers(path):
                            self.seen.setdefault(path, None)
            elif covers(entry.name) and entry.path not in self.seen:
                self.seen[entry.path] = None

    def _note(self, directory):
        if directory not in self.directories:
            self.directories[directory] = _mtime(directory)

    def _note_parents(self, path):
        directory = os.path.dirname(path)
        while directory.startswith(self._inside):
            if directory in self.directories:
                return
            self._note(directory)
            directory = os.path.dirname(directory)


def listing(root):
    """Files under `root` that git sees, tracked or not but never ignored.

    Inside Vis, the host lists the workspace once for every extension that
    asks, without a child process. Elsewhere, git runs as a confined child and
    reads no global config. A jail can refuse the user's ``~/.gitconfig``, and
    git then lists nothing. Where git cannot list the tree, a bounded walk that
    skips hidden and build directories stands in.
    """
    root = Path(root)
    shared = _shared_listing(root)
    if shared is not None:
        return shared
    try:
        done = process.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            timeout_s=60,
            env={"GIT_CONFIG_GLOBAL": os.devnull},
        )
        if done.is_ok:
            inside = os.path.join(root, "")
            return [inside + name for name in done.out.split("\0") if name]
    except (process.ToolMissing, process.ToolTimeout, OSError):
        pass
    return walked(root)


def _shared_listing(root):
    """The host's listing of the session workspace, or None where it has none.

    The host answers only for its own workspace root, and a host older than
    `vis.workspace_files` has no listing at all.
    """
    listing = getattr(vis, "workspace_files", None)
    if listing is None or not process.is_hosted():
        return None
    try:
        if Path(vis.workspace_root()) != root:
            return None
        files = listing()
    except Exception:
        return None
    return None if files is None else [os.fspath(path) for path in files]


def walked(start, tree=None):
    """Files under `start`, skipping hidden and build directories, in bounded steps.

    With `tree`, every directory walked is noted there, so later stat calls see
    the entries it gains.
    """
    found, pending, visited = [], [os.fspath(start)], 0
    while pending and visited < MOST_ENTRIES:
        directory = pending.pop()
        if tree is not None:
            tree._note(directory)
        try:
            with os.scandir(directory) as entries:
                listed = list(entries)
        except OSError:
            continue
        for entry in listed:
            visited += 1
            if entry.is_dir(follow_symlinks=False):
                if _walkable(entry.name):
                    pending.append(entry.path)
            elif entry.is_file(follow_symlinks=False):
                found.append(entry.path)
    return found


def _walkable(name):
    return not name.startswith(".") and name not in IGNORED_DIRECTORIES


def stamp_of(path):
    """`(mtime_ns, size)` of a file, or None when it is gone."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _mtime(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None
