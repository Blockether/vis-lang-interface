"""A language runtime that outlives the call that started it.

`vis-lang-python` keeps one interpreter holding the REPL's globals;
`vis-lang-clojure` keeps one JVM owning every nREPL it started. Both speak the
same shape of protocol with their runtime: one JSON request per line in, one
JSON answer per line out.

Those two lines cannot be the child's own stdin and stdout any more. Everything
a language extension starts goes through `vis.jailed_shell`, and a shell child
runs under a pty that merges stdout with stderr and normalizes what passes
through — a framed protocol does not survive that. So the extension arranges a
rendezvous instead: a private directory holding two FIFOs, handed to that one
child as its stdin and stdout and granted to it by name. The child keeps reading
lines from stdin and writing lines to stdout, exactly as before; the pty log
keeps whatever the runtime says about itself, which is what a failed start hands
back.

Closing the request FIFO is what ends a runtime, so an extension that goes away
never leaves an interpreter behind.
"""

from __future__ import annotations

import json
import os
import queue
import select
import shlex
import shutil
import tempfile
import threading
import time

from vis_lang_interface.process import RUN_PREFIX, is_hosted, spawn, tool_path

DEFAULT_TIMEOUT_S = 120.0
"""Seconds `request` waits for an answer when the caller names no budget."""

SPAWN_WAIT_S = 1
"""Seconds the spawning call waits before the runtime becomes a background child."""

LOG_TAIL_LINES = 40
"""Lines of the runtime's own output a failure hands back."""

_LIVENESS_STEP_S = 0.5
"""First pause between two checks of whether the runtime is still there."""

_LIVENESS_MAX_S = 5.0
"""Longest pause between two of those checks, once a call settles in to wait."""

_READ_POLL_S = 0.1
"""How long the reader waits on a quiet rendezvous before looking again."""


class RuntimeGone(RuntimeError):
    """The runtime stopped, or never started, instead of answering."""


class Rendezvous:
    """The private FIFO pair a runtime reads its requests and writes its answers on.

    Both FIFOs are opened here before the child arrives, so neither side ever
    waits for the other to show up. The request end is held read-write, which is
    what makes opening it return at once and makes dropping it the EOF the
    runtime shuts down on. The answer end is read without blocking, so closing
    this rendezvous is never a race against a reader stuck in the middle of a
    line.
    """

    def __init__(self, name="runtime"):
        self.path = tempfile.mkdtemp(prefix=f"{RUN_PREFIX}{name}-")
        self.requests = os.path.join(self.path, "requests")
        self.answers = os.path.join(self.path, "answers")
        os.mkfifo(self.requests, 0o600)
        os.mkfifo(self.answers, 0o600)
        self.closing = threading.Event()
        self._to_runtime = None
        self._from_runtime = None

    def open(self):
        """Hold both ends, so the child's own open of either never waits."""
        self._to_runtime = os.open(self.requests, os.O_RDWR)
        self._from_runtime = os.open(self.answers, os.O_RDONLY | os.O_NONBLOCK)
        return self

    def write(self, line):
        """Send one framed line to the runtime."""
        os.write(self._to_runtime, (line + "\n").encode("utf-8"))

    def place(self, name, text):
        """Put a file of the runtime's own next to its FIFOs.

        A runtime started from a source file — a driver, a script — is handed
        that file here rather than on a command line the shell would have to
        carry intact.

        Args:
            name: File name inside the rendezvous directory.
            text: What the file holds.

        Returns:
            The path the file was written to.
        """
        where = os.path.join(self.path, name)
        with open(where, "w", encoding="utf-8") as opened:
            opened.write(text)
        return where

    def lines(self):
        """Every line the runtime writes, until this rendezvous is closed."""
        held = b""
        while not self.closing.is_set():
            if not select.select([self._from_runtime], [], [], _READ_POLL_S)[0]:
                continue
            try:
                chunk = os.read(self._from_runtime, 65536)
            except BlockingIOError:
                continue
            except (OSError, ValueError):
                return
            if not chunk:
                # Nobody holds the writing end right now: the runtime has not
                # opened it yet, or it is gone. Whether it is gone is the shell
                # handle's answer, not this loop's.
                time.sleep(_READ_POLL_S)
                continue
            held += chunk
            while b"\n" in held:
                line, held = held.split(b"\n", 1)
                yield line.decode("utf-8", "replace")

    def close(self):
        """Stop reading, drop both ends and remove the directory holding them."""
        self.closing.set()
        for descriptor in (self._to_runtime, self._from_runtime):
            try:
                if descriptor is not None:
                    os.close(descriptor)
            except OSError:
                pass
        self._to_runtime = self._from_runtime = None
        shutil.rmtree(self.path, ignore_errors=True)


class Runtime:
    """One live language runtime and the framed conversation with it."""

    def __init__(self, handle, meeting, command, cwd):
        self.shell = handle
        self.command = tuple(command)
        self.cwd = str(cwd) if cwd else None
        self.started_at = time.time()
        self._meeting = meeting
        self._answers: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._pump, name="vis-lang-runtime", daemon=True
        )
        self._thread.start()

    @property
    def id(self):
        """Id of the shell this runtime runs under."""
        return self.shell.get("id")

    @property
    def pid(self):
        """Process id of the runtime itself."""
        return self.shell.get("pid")

    @property
    def exit_code(self):
        """What the runtime exited with, or None while it is still running."""
        try:
            return self.shell.logs(-1).get("exit")
        except Exception:
            return None

    @property
    def is_running(self):
        """Whether the runtime is still there, asked of the shell that owns it."""
        try:
            return str(self.shell.logs(-1).get("status")) == "running"
        except Exception:
            return False

    def log_tail(self, lines=LOG_TAIL_LINES):
        """The last lines the runtime printed for itself, blank ones dropped.

        Args:
            lines: How many lines to read back.

        Returns:
            The lines, oldest first.
        """
        try:
            said = str(self.shell.logs(-int(lines)).get("out") or "")
        except Exception:
            return []
        return [line for line in said.splitlines() if line.strip()]

    def request(self, payload, timeout_s=DEFAULT_TIMEOUT_S, *, wants=None):
        """Send one request and wait for its answer.

        Args:
            payload: The request, as JSON-safe data.
            timeout_s: Seconds to wait for the answer.
            wants: The `id` the answer must carry, for a runtime that serves
                more than one call at a time. None takes the next answer.

        Returns:
            The answer, whether it reports success or failure.

        Raises:
            RuntimeGone: The runtime stopped before answering.
            TimeoutError: The deadline passed with no answer.
        """
        with self._lock:
            if not self.is_running:
                raise RuntimeGone(self._stopped())
            try:
                self._meeting.write(json.dumps(payload))
            except (OSError, ValueError, AttributeError) as exc:
                raise RuntimeGone(self._stopped()) from exc
            deadline = time.monotonic() + float(timeout_s)
            pause = _LIVENESS_STEP_S
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(
                        f"{self.command[0]} did not answer within {timeout_s:g}s"
                    )
                try:
                    line = self._answers.get(timeout=min(pause, left))
                except queue.Empty:
                    # A runtime that died mid-call never answers: say so now
                    # instead of holding the caller to the whole budget.
                    if not self.is_running:
                        raise RuntimeGone(self._stopped()) from None
                    pause = min(pause * 2, _LIVENESS_MAX_S)
                    continue
                if line is None:
                    raise RuntimeGone(self._stopped())
                try:
                    answer = json.loads(line)
                except ValueError:
                    # Not an answer: the runtime printed something of its own on
                    # the channel. The pty log already has it.
                    continue
                if wants is None or str(answer.get("id")) == str(wants):
                    return answer

    def stop(self):
        """End the runtime, and with it everything it owns.

        Closing the rendezvous is the EOF it shuts down on; the shell it runs
        under is stopped afterwards, so a runtime that ignores EOF still goes.
        """
        self._meeting.closing.set()
        self._thread.join(_LIVENESS_MAX_S)
        self._meeting.close()
        try:
            self.shell.wait(5)
        except Exception:
            pass
        try:
            self.shell.stop()
        except Exception:
            # An exited runtime has no entry left to stop, which is the outcome
            # this method wanted.
            pass

    def _pump(self):
        """Carry every line the runtime writes into the answer queue."""
        try:
            for line in self._meeting.lines():
                text = line.strip()
                if text:
                    self._answers.put(text)
        except (OSError, ValueError):
            pass
        finally:
            self._answers.put(None)

    def _stopped(self):
        """Why a call has no answer, with the last words the runtime said."""
        said = "\n".join(self.log_tail()[-3:])
        where = f" for {self.cwd}" if self.cwd else ""
        return f"the {self.command[0]} runtime{where} stopped before answering" + (
            f"\n{said}" if said else ""
        )


def start(command, *, cwd=None, env=None, read_write=(), name="runtime", meeting=None):
    """Start `command` as a confined runtime listening on its own rendezvous.

    The child is spawned through the workspace jail with its stdin and stdout
    already wired to the rendezvous, and the rendezvous directory is granted to
    it by name. `VIS_LANG_RENDEZVOUS` names that directory for a runtime that
    wants to know where it is.

    Args:
        command: Program and arguments for the runtime.
        cwd: Directory the runtime runs in.
        env: Variables for it, over the ones it inherits; None unsets a name.
        read_write: Further paths outside the session's roots it may use.
        name: What this runtime is, used in the rendezvous directory's name.
        meeting: A rendezvous already opened and filled by the caller, for a
            runtime started from a file placed next to its FIFOs. Starting
            takes it over, closing it if the runtime never comes up.

    Returns:
        The live `Runtime`.

    Raises:
        ToolMissing: The program is not installed.
    """
    argv = [str(part) for part in command]
    meeting = meeting or Rendezvous(name).open()
    try:
        if os.sep not in argv[0]:
            tool_path(argv[0])
        line = (
            f"exec {shlex.join(argv)} <{shlex.quote(meeting.requests)}"
            f" >{shlex.quote(meeting.answers)}"
        )
        handle = spawn(
            line,
            cwd=cwd,
            env={**dict(env or {}), "VIS_LANG_RENDEZVOUS": meeting.path},
            # Inside Vis this is only how long the spawning call waits: the
            # runtime keeps running under its handle afterwards. The local host
            # outside Vis reads the same key as a kill deadline, and a runtime
            # is meant to outlive its start, so out there it stays unset.
            timeout_s=SPAWN_WAIT_S if is_hosted() else None,
            read_write=[meeting.path, *read_write],
        )
        return Runtime(handle, meeting, argv, cwd)
    except BaseException:
        meeting.close()
        raise


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "LOG_TAIL_LINES",
    "Rendezvous",
    "Runtime",
    "RuntimeGone",
    "start",
]
