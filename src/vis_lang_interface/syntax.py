"""Check changed files and apply validated structural repairs through edit hooks.

The language extension supplies its parser and optional repair callback.

After a Python block, the guard checks changed files and can repair them.
Each repair uses a separate atomic replacement and checks for concurrent changes.
The block's earlier writes are not transactional and cannot be rolled back.
Unresolved errors and completed repairs reach the next request through ``ctx``.

Inside Vis, the guard keeps its work off the block's path. The first ``ctx``
call lists the workspace and builds the file tree in a background thread. After
a block, a background thread checks and repairs the changed files. The next
guard call waits for that thread, then stores its report. Background threads
never call the host.

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
from contextlib import contextmanager
from pathlib import Path

import blockether.vis.extension as vis

from vis_lang_interface import process
from vis_lang_interface.results import SyntaxResult
from vis_lang_interface.tree import Tree as _Tree
from vis_lang_interface.tree import listing as _listing
from vis_lang_interface.tree import stamp_of as _stamp

# A tree is listed again at most this often; stat calls keep it current between listings.
REFRESH_S = 300.0
# Most files the session context names.
MOST_REPORTED = 20
# After the parser fails, the guard stops asking it for this long.
QUIET_S = 120.0
# Longest time `ctx` waits for the post-block check. A longer check reports later.
CONTEXT_WAIT_S = 0.1
# A guard call or check that takes this long logs where its time went.
SLOW_S = 0.1


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
            one-based line numbers in the changed text. Return an object with
            ``source`` and nonempty ``notes``, or None. The parser must accept
            the complete result. ``original`` is None: a Python block gives
            no source from before its writes.
        most_files: Most changed files one operation parses again. The rest
            wait for the next operation.
        workspace_root: Function returning the session's working copy;
            `vis.workspace_root` by default.
        state: Mapping that keeps the report between calls; `vis.state` by
            default.
        background: Whether listings and post-block checks run in background
            threads; by default only inside a Vis host.
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
        background=None,
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
        self._background = process.is_hosted() if background is None else background
        # Root -> (thread, errors) that builds its tree; the post-block check in flight.
        self._building = {}
        self._job = None
        # Log lines of a background thread, which must not call the host.
        self._local = threading.local()

    def covers(self, path):
        """Whether the parser reads `path`, judged by its name."""
        return str(path).lower().endswith(self.suffixes)

    def op_hooks(self):
        """The hooks to pass as `vis.Extension(op_hooks=...)`."""
        return (
            vis.OpHook(["py3"], self.before_block),
            vis.OpHook(["py3"], self.after_edit, phase="after"),
        )

    def before_block(self, call):
        """List the workspace's files before a Python block can change them."""
        timing = _Timing()
        try:
            with self._lock:
                self._settle(timing=timing)
                with timing.wait("host"):
                    root = Path(self._workspace_root())
                self._tree(root, timing)
        except Exception as error:
            self._log("before py3", error)
        self._log_timing("before py3", timing)
        return None

    def after_edit(self, call):
        """Parse again what a Python block changed, and keep the report."""
        timing = _Timing()
        try:
            with timing.wait("host"):
                root = Path(self._workspace_root())
            with self._lock:
                self._settle(timing=timing)
                if call.get("result") is None:
                    pass
                elif self._background:
                    self._start_check(root, timing)
                else:
                    self._recheck(
                        root, self._tree(root, timing).changes(self.covers), repair=True
                    )
        except Exception as error:
            self._log(f"after {call.get('op')}", error)
        self._log_timing(f"after {call.get('op')}", timing)
        return None

    def ctx(self, env=None):
        """Session context naming the files under the workspace that do not parse.

        The context waits at most `CONTEXT_WAIT_S` for the check of the last
        block. When that check still runs, the context gives the report from
        before the block and says so; the next guard call stores the new report.
        """
        timing = _Timing()
        try:
            with timing.wait("host"):
                root = self._context_root(env)
            with self._lock:
                checked = self._settle(CONTEXT_WAIT_S, timing)
                # The check in flight uses the tree; a new listing waits for it.
                if self._background and checked:
                    self._prewarm(root, timing)
            with timing.wait("host"):
                report = self._report(root)
                repairs = self._state.get(f"{self.language}_syntax_repairs:{root}", [])
        except Exception as error:
            self._log("context", error)
            return {}
        finally:
            self._log_timing("context", timing)
        rows = [
            f"{path}:{row.get('line', 0)}:{row.get('column', 0)}: {row.get('message', '')}"
            for path, row in sorted(report.items())
        ]
        if len(rows) > MOST_REPORTED:
            hidden = len(rows) - MOST_REPORTED
            rows = [*rows[:MOST_REPORTED], f"... and {hidden} more files"]
        context: dict[str, list[str] | str] = {self.key: rows} if rows else {}
        if repairs:
            context[f"{self.language}_syntax_repairs"] = repairs
        if not checked:
            context[f"{self.language}_syntax_check"] = (
                "running: the errors are from before the last Python block"
            )
        return context

    def _context_root(self, env):
        """The workspace root of a `ctx` call.

        Vis puts the value of `vis.workspace_root()` in `env` as `session_root`, so
        the default guard reads it there and saves one host call. Without that key,
        or with its own `workspace_root`, the guard still asks that function.
        """
        env = env if isinstance(env, Mapping) else {}
        given = env.get("session_root")
        if given and self._workspace_root is vis.workspace_root:
            return Path(given)
        return Path(self._workspace_root())

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

    def _recheck(self, root, changed, *, repair=False):
        """Parse the `{path: stamp}` files again and store what still does not parse."""
        self._keep(root, *self._rechecked(root, self._report(root), changed, repair))

    def _rechecked(self, root, report, changed, repair):
        """The new report and repair notes, without the host.

        The repair notes are None when the parser was unavailable after a
        repair, so the stored notes stay unchanged.
        """
        report = dict(report)
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
                    return report, None
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
        return report, repairs

    def _keep(self, root, report, repairs):
        """Store a report and, unless they are None, its repair notes."""
        self._store(root, report)
        if repairs is None:
            return
        key = f"{self.language}_syntax_repairs:{root}"
        if repairs:
            self._state[key] = repairs
        elif self._state.get(key):
            del self._state[key]

    def _start_check(self, root, timing):
        """Check what the block changed in a background thread; `_settle` stores it."""
        report = self._report(root)
        tree = self._tree(root, timing)
        tree.read_moved(self.covers)
        job = {"root": root, "result": None, "logs": [], "timing": None}

        def check():
            self._local.logs = job["logs"]
            timing = _Timing()
            changed = {}
            try:
                changed = tree.changes(self.covers, read=False)
                job["result"] = self._rechecked(root, report, changed, True)
            except Exception as error:
                job["logs"].append(("after py3", error))
            timing.stop()
            job["timing"] = (timing, len(changed))

        job["thread"] = threading.Thread(
            target=check, name=f"vis-{self.language}-syntax-check", daemon=True
        )
        self._job = job
        job["thread"].start()

    def _settle(self, wait=None, timing=None):
        """Wait for the post-block check in flight, then store its report and logs.

        With `wait`, stop waiting after that many seconds and keep the check in
        flight. Returns whether no check is in flight now.
        """
        job = self._job
        if job is None:
            return True
        with timing.wait("check") if timing else _no_wait():
            job["thread"].join(wait)
        if job["thread"].is_alive():
            return False
        self._job = None
        for where, error in job["logs"]:
            self._log(where, error)
        if job["timing"] is not None:
            check, files = job["timing"]
            self._log_timing(f"check of {files} files", check)
        if job["result"] is not None:
            self._keep(job["root"], *job["result"])
        return True

    def _prewarm(self, root, timing):
        """List `root` here and build its tree in a background thread."""
        key = str(root)
        tree = self._trees.get(key)
        if key in self._building or (
            tree is not None and time.monotonic() - tree.listed_at <= REFRESH_S
        ):
            return
        with timing.wait("listing"):
            files = _listing(root)
        logs = []

        def build():
            try:
                self._trees[key] = _Tree(root, files, self.covers, tree)
            except Exception as error:
                logs.append(error)

        thread = threading.Thread(
            target=build, name=f"vis-{self.language}-syntax-listing", daemon=True
        )
        self._building[key] = (thread, logs)
        thread.start()

    def _tree(self, root, timing):
        """The listed files under `root`, listed again when the listing is old."""
        building = self._building.pop(str(root), None)
        if building is not None:
            thread, logs = building
            with timing.wait("tree"):
                thread.join()
            for error in logs:
                self._log("listing", error)
        tree = self._trees.get(str(root))
        if tree is None or time.monotonic() - tree.listed_at > REFRESH_S:
            with timing.wait("listing"):
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

    def _log_timing(self, where, timing):
        """Log where a slow call spent its time; a background thread never logs."""
        line = timing.line()
        if line is None or getattr(self._local, "logs", None) is not None:
            return
        try:
            vis.log("info", f"{self.language} syntax guard, {where}: {line}")
        except Exception:
            pass

    def _log(self, where, error):
        logs = getattr(self._local, "logs", None)
        if logs is not None:
            logs.append((where, error))
            return
        try:
            vis.log("warn", f"{self.language} syntax guard, {where}: {error}")
        except Exception:
            pass


class _Timing:
    """Where one guard call spent its time, for one log line.

    Each named wait counts its clock time. `cpu` is the time this thread ran.
    `gil` is the rest of the time this thread did not run outside the named
    waits. The guard does no other I/O there, so this is mostly the time the
    thread waited for the GIL while other threads of the worker ran.
    """

    def __init__(self):
        self._started = time.perf_counter()
        self._cpu = time.thread_time()
        self.waits = {}
        self._waits_cpu = 0.0
        self._stopped = None

    @contextmanager
    def wait(self, name):
        """Count the clock time of the `with` body as the wait `name`."""
        started, cpu = time.perf_counter(), time.thread_time()
        try:
            yield
        finally:
            self.waits[name] = self.waits.get(name, 0.0) + (
                time.perf_counter() - started
            )
            self._waits_cpu += time.thread_time() - cpu

    def stop(self):
        """End the call here, on its own thread; `line` may run later on another."""
        self._stopped = (
            time.perf_counter() - self._started,
            time.thread_time() - self._cpu,
        )

    def line(self, slow=None):
        """The log line, or None when the call took less than `slow` seconds."""
        if self._stopped is None:
            self.stop()
        assert self._stopped is not None
        wall, cpu = self._stopped
        if wall < (SLOW_S if slow is None else slow):
            return None
        waited = sum(self.waits.values())
        gil = max(0.0, wall - waited - (cpu - self._waits_cpu))
        parts = [("total", wall), ("cpu", cpu), *self.waits.items(), ("gil", gil)]
        return " ".join(f"{name}={seconds * 1000:.0f}ms" for name, seconds in parts)


@contextmanager
def _no_wait():
    yield


def _shown(root, path):
    """`path` as the report names it: relative to `root` when inside it."""
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)


def _absolute(root, shown):
    path = Path(shown)
    return path if path.is_absolute() else Path(root) / path
