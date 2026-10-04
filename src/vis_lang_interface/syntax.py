"""Check changed files and apply validated structural repairs through edit hooks.

The language extension supplies its parser and optional repair callback.
Before a patch writes, a repair decision replaces the proposed source.
The host writes that validated source once and reports the corrections.
Without a valid repair, a patch that breaks a parseable file is refused.

After a Python block, the guard checks changed files and can repair them.
Each repair uses a separate atomic replacement and checks for concurrent changes.
The block's earlier writes are not transactional and cannot be rolled back.
Unresolved errors and completed repairs reach the next request through ``ctx``.

The guard has no parser. If its parser is unavailable, it allows the operation
and logs the failure. An unavailable parser never authorizes a repair.
"""

from __future__ import annotations

import difflib
import os
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import blockether.vis.extension as vis

from vis_lang_interface import process
from vis_lang_interface.project import IGNORED_DIRECTORIES
from vis_lang_interface.results import SyntaxResult

# A tree is listed again at most this often; stat calls keep it current between listings.
REFRESH_S = 300.0
# Most directory entries one walk visits where git cannot list the tree.
MOST_ENTRIES = 20_000
# Most files the session context names.
MOST_REPORTED = 20
# After the parser fails, the guard stops asking it for this long.
QUIET_S = 120.0


def _read_source(path):
    """Read source without changing its line endings."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return stream.read()


class SyntaxGuard:
    """Check edits, propose validated repairs and report unresolved errors.

    Args:
        language: Language name as results spell it, such as `"clojure"`.
        suffixes: File name endings the parser reads, such as `(".clj", ".edn")`.
        check: Private callback of `{path: text}` and the workspace root that
            returns the parser's `SyntaxResult`. Each diagnostic names the path
            it was given. Register the guard's hooks, not this callback as a tool.
        repair: Optional callback of ``source``, with keyword arguments
            ``original``, ``spans`` and ``parses_clean``. Spans use inclusive,
            one-based line numbers in the proposed text. Return an object with
            ``source`` and nonempty ``notes``, or None. The parser must accept
            the complete result. A post-block repair has no original source.
        most_files: Most changed files one operation parses again. The rest
            wait for the next operation.
        workspace_root: Function returning the session's working copy;
            `vis.workspace_root` by default.
        state: Mapping that keeps the report between calls; `vis.state` by
            default.
    """

    def __init__(
        self,
        language,
        suffixes,
        check: Callable[[Mapping[str, str], Path], SyntaxResult],
        *,
        repair=None,
        most_files=200,
        workspace_root=None,
        state=None,
    ):
        self.language = str(language)
        self.suffixes = tuple(str(suffix).lower() for suffix in suffixes)
        if not self.suffixes:
            raise ValueError("SyntaxGuard needs at least one file suffix")
        self.key = f"{self.language}_syntax_errors"
        self.most_files = max(1, int(most_files))
        self._check = check
        self._repair = repair
        self._workspace_root = workspace_root or vis.workspace_root
        self._state = vis.state if state is None else state
        self._trees = {}
        self._lock = threading.Lock()
        self._quiet_until = 0.0

    def covers(self, path):
        """Whether the parser reads `path`, judged by its name."""
        return str(path).lower().endswith(self.suffixes)

    def op_hooks(self):
        """The hooks to pass as `vis.Extension(op_hooks=...)`."""
        return (
            vis.OpHook(["patch"], self.before_patch),
            vis.OpHook(["python_execution"], self.before_block),
            vis.OpHook(["patch", "python_execution"], self.after_edit, phase="after"),
        )

    def before_patch(self, call):
        """Repair a proposed patch, or refuse it if it breaks a parseable file."""
        try:
            return self._refusal(call.get("preview"))
        except Exception as error:
            self._log("before patch", error)
            return None

    def before_block(self, call):
        """List the workspace's files before a Python block can change them."""
        try:
            with self._lock:
                self._tree(Path(self._workspace_root()))
        except Exception as error:
            self._log("before python_execution", error)
        return None

    def after_edit(self, call):
        """Parse again what a patch or a Python block changed, and keep the report."""
        try:
            root = Path(self._workspace_root())
            with self._lock:
                if call.get("op") == "patch":
                    if call.get("result") is not None:
                        self._recheck(root, self._patched(call.get("args"), root))
                elif call.get("result") is not None:
                    self._recheck(
                        root, self._tree(root).changes(self.covers), repair=True
                    )
        except Exception as error:
            self._log(f"after {call.get('op')}", error)
        return None

    def ctx(self, env=None):
        """Session context naming the files under the workspace that do not parse."""
        try:
            root = Path(self._workspace_root())
            report = self._report(root)
            repairs = self._state.get(f"{self.language}_syntax_repairs:{root}", [])
        except Exception as error:
            self._log("context", error)
            return {}
        rows = [
            f"{path}:{row.get('line', 0)}:{row.get('column', 0)}: {row.get('message', '')}"
            for path, row in sorted(report.items())
        ]
        if len(rows) > MOST_REPORTED:
            hidden = len(rows) - MOST_REPORTED
            rows = [*rows[:MOST_REPORTED], f"... and {hidden} more files"]
        context = {self.key: rows} if rows else {}
        if repairs:
            context[f"{self.language}_syntax_repairs"] = repairs
        return context

    def _refusal(self, preview):
        """Return a repair or refusal for an invalid preview, otherwise None."""
        if not isinstance(preview, Mapping):
            return None
        path, before, after = (
            preview.get(name) for name in ("path", "before", "after")
        )
        if not all(isinstance(value, str) for value in (path, before, after)):
            return None
        if before == after or not self.covers(path):
            return None
        root = Path(self._workspace_root())
        broken = self._ask({path: after}, root)
        if not broken:
            return None
        candidate = self._candidate(
            path, after, root, original=before, spans=preview.get("spans", [])
        )
        if candidate:
            return candidate
        if self._ask({path: before}, root) != ():
            return None
        row = broken[0]
        reason = (
            f"{_location(row)}: {row.message}. This patch would make {path} "
            f"unparseable, so nothing was written."
        )
        hint = (
            f"The file parses now. Change the edits so that the {self.language} "
            "parser still reads it, then patch again."
        )
        return _block(reason, hint)

    def _candidate(self, path, source, root, *, original, spans):
        """Accept a language repair only when its final source passes the parser."""
        if self._repair is None or not spans:
            return None
        verdicts = {source: False}

        def parses_clean(text):
            if text not in verdicts:
                verdicts[text] = self._ask({path: text}, root) == ()
            return verdicts[text]

        try:
            candidate = self._repair(
                source, original=original, spans=spans, parses_clean=parses_clean
            )
            if (
                candidate is not None
                and isinstance(candidate.source, str)
                and candidate.source != source
                and isinstance(candidate.notes, (list, tuple))
                and candidate.notes
                and all(
                    isinstance(note, str) and note.strip() for note in candidate.notes
                )
                and parses_clean(candidate.source)
            ):
                return {
                    "marker": "repair",
                    "source": candidate.source,
                    "notes": list(candidate.notes),
                }
        except Exception as error:
            self._log("repair", error)
        return None

    def _write_repair(self, path, before, after):
        """Replace a changed regular file once, only while its source still matches."""
        temporary = None
        try:
            if path.is_symlink() or _read_source(path) != before:
                return False
            mode = path.stat().st_mode & 0o7777
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=path.parent,
                prefix=f".{path.name}.vis-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(mode)
            if path.is_symlink() or _read_source(path) != before:
                return False
            os.replace(temporary, path)
            return True
        except OSError as error:
            self._log("repair write", error)
            return False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _ask(self, sources, root):
        """The parser's diagnostics for `sources`, or None when it cannot be asked."""
        if time.monotonic() < self._quiet_until:
            return None
        try:
            result = self._check(dict(sources), root)
            return tuple(result.diagnostics)
        except Exception as error:
            self._quiet_until = time.monotonic() + QUIET_S
            self._log("parser", error)
            return None

    def _patched(self, args, root):
        """`{path: stamp}` for the file a patch call wrote, when the parser reads it."""
        if not isinstance(args, (list, tuple)) or not args:
            return {}
        if not isinstance(args[0], str):
            return {}
        path = Path(args[0]).expanduser()
        path = path if path.is_absolute() else root / path
        if not self.covers(path):
            return {}
        return {str(path): _stamp(path)}

    def _recheck(self, root, changed, *, repair=False):
        """Parse the `{path: stamp}` files again and store what still does not parse."""
        report = dict(self._report(root))
        for shown in [
            shown for shown in report if not _absolute(root, shown).is_file()
        ]:
            del report[shown]
        tree = self._trees.get(str(root))
        sources, stamps = {}, {}
        repairs = []
        for path in sorted(changed)[: self.most_files]:
            shown = _shown(root, path)
            try:
                sources[shown] = _read_source(path)
            except (OSError, UnicodeDecodeError):
                report.pop(shown, None)
                if tree:
                    tree.seen.pop(path, None)
                continue
            stamps[path] = changed[path]
        if sources:
            rows = self._ask(sources, root)
            if rows is not None:
                if repair and self._repair is not None:
                    for shown in dict.fromkeys(row.path for row in rows):
                        source = sources[shown]
                        candidate = self._candidate(
                            shown,
                            source,
                            root,
                            original=None,
                            spans=[[1, max(1, len(source.splitlines()))]],
                        )
                        path = _absolute(root, shown)
                        if candidate and self._write_repair(
                            path, source, candidate["source"]
                        ):
                            delta = "".join(
                                difflib.unified_diff(
                                    source.splitlines(keepends=True),
                                    candidate["source"].splitlines(keepends=True),
                                    fromfile=shown,
                                    tofile=shown,
                                )
                            )
                            repairs.append(
                                f"{shown}: {' '.join(candidate['notes'])}\n{delta}"
                            )
                        try:
                            sources[shown] = _read_source(path)
                            stamps[str(path)] = _stamp(path)
                        except (OSError, UnicodeDecodeError):
                            sources.pop(shown, None)
                    rows = self._ask(sources, root)
                if rows is None:
                    self._store(root, report)
                    return
                for shown in sources:
                    report.pop(shown, None)
                for row in rows:
                    report[row.path] = {
                        "line": row.line,
                        "column": row.column,
                        "message": row.message,
                    }
                if tree:
                    tree.seen.update(stamps)
        self._store(root, report)
        key = f"{self.language}_syntax_repairs:{root}"
        if repairs:
            self._state[key] = repairs
        elif self._state.get(key):
            del self._state[key]

    def _tree(self, root):
        """The listed files under `root`, listed again when the listing is old."""
        tree = self._trees.get(str(root))
        if tree is None or time.monotonic() - tree.listed_at > REFRESH_S:
            tree = _Tree(root, _listing(root), self.covers, tree)
            self._trees[str(root)] = tree
        return tree

    def _state_key(self, root):
        return f"{self.key}:{root}"

    def _report(self, root):
        report = self._state.get(self._state_key(root))
        return dict(report) if report else {}

    def _store(self, root, report):
        key = self._state_key(root)
        if report:
            self._state[key] = report
        elif self._state.get(key):
            del self._state[key]

    def _log(self, where, error):
        try:
            vis.log("warn", f"{self.language} syntax guard, {where}: {error}")
        except Exception:
            pass


class _Tree:
    """Files under one root as last seen: listed once, then kept current by stat.

    `seen` maps each file the parser reads to the `(mtime_ns, size)` it had when
    it was listed or last parsed; None marks a file that was never parsed. A
    directory whose own mtime moved gained or lost entries, so only those
    directories are read again.
    """

    def __init__(self, root, files, covers, previous=None):
        self.root = Path(root)
        self.listed_at = time.monotonic()
        self.seen = {}
        self.directories = {}
        known = previous.seen if previous else None
        self._note(self.root)
        for path in files:
            self._note_parents(path)
            if covers(path):
                key = str(path)
                if known is None:
                    self.seen[key] = _stamp(path)
                else:
                    self.seen[key] = known.get(key)

    def changes(self, covers):
        """`{path: stamp}` for every file the parser reads that changed since seen."""
        for directory, stamp in list(self.directories.items()):
            now = _mtime(directory)
            if now is None:
                del self.directories[directory]
            elif now != stamp:
                self.directories[directory] = now
                self._read(Path(directory), covers)
        changed = {}
        for path, stamp in self.seen.items():
            now = _stamp(Path(path))
            if now != stamp or stamp is None:
                changed[path] = now
        return changed

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
                    for path in _walked(Path(entry.path), self):
                        if covers(path):
                            self.seen.setdefault(str(path), None)
            elif covers(entry.name) and entry.path not in self.seen:
                self.seen[entry.path] = None

    def _note(self, directory):
        key = str(directory)
        if key not in self.directories:
            self.directories[key] = _mtime(key)

    def _note_parents(self, path):
        directory = Path(path).parent
        while directory != self.root and self.root in directory.parents:
            if str(directory) in self.directories:
                return
            self._note(directory)
            directory = directory.parent


def _listing(root):
    """Files under `root` that git sees, tracked or not but never ignored.

    Where git cannot list the tree, a bounded walk that skips hidden and build
    directories stands in.
    """
    root = Path(root)
    try:
        done = process.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            timeout_s=60,
        )
        if done.is_ok:
            return [root / name for name in done.out.split("\0") if name]
    except (process.ToolMissing, process.ToolTimeout, OSError):
        pass
    return _walked(root)


def _walked(start, tree=None):
    """Files under `start`, skipping hidden and build directories, in bounded steps.

    With `tree`, every directory walked is noted there, so later stat calls see
    the entries it gains.
    """
    found, pending, visited = [], [Path(start)], 0
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
                    pending.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                found.append(Path(entry.path))
    return found


def _walkable(name):
    return not name.startswith(".") and name not in IGNORED_DIRECTORIES


def _stamp(path):
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


def _shown(root, path):
    """`path` as the report names it: relative to `root` when inside it."""
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)


def _absolute(root, shown):
    path = Path(shown)
    return path if path.is_absolute() else Path(root) / path


def _location(row):
    """`path:line:column`, leaving out what the parser did not locate."""
    parts = [row.path or "<source>"]
    if row.line:
        parts.append(str(row.line))
        if row.column:
            parts.append(str(row.column))
    return ":".join(parts)


def _block(reason, hint):
    """`vis.block` carrying a hint, on a Vis host whose `block` takes one."""
    try:
        return vis.block(reason, hint=hint)
    except TypeError:
        return vis.block(f"{reason} {hint}")
