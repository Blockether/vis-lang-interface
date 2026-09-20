"""Running a language toolchain as a child process.

Everything a language extension starts goes through `vis.jailed_shell`, so
whatever confinement the person running Vis turned on covers the toolchain as
much as the model's own shell. A jailed toolchain still reaches the package
indexes it needs: Maven, Clojars and PyPI answer through the egress proxy.

These helpers stay deliberately narrow: one command, one timeout, captured
output, and an error that names the missing program instead of a bare exit code.

A shell child runs under a pty, with stdout and stderr merged into one
normalized stream. Tool output is data — JSON from ruff, EDN from clj-kondo — so
nothing here reads that stream: the command writes its own streams into a
private run directory granted to that one child, and the files are read back
when it is done.
"""

from __future__ import annotations

import math
import os
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import blockether.vis.extension as vis

RUN_PREFIX = "vis-lang-"
"""Prefix of the private directory one run reads and writes through."""


class ToolMissing(RuntimeError):
    """A program the language needs is not installed."""


class ToolTimeout(RuntimeError):
    """A program was still running when its deadline passed."""


@dataclass(frozen=True)
class ToolRun:
    """What a finished child process left behind."""

    command: Annotated[tuple[str, ...], "Command that ran."]
    exit_code: Annotated[int, "Process exit status."]
    out: Annotated[str, "Standard output."]
    err: Annotated[str, "Standard error."]
    duration_ms: Annotated[int, "Wall time in milliseconds."]

    @property
    def is_ok(self):
        """Whether the process exited with status 0."""
        return self.exit_code == 0


def tool_path(program, hint=""):
    """Absolute path of `program` on PATH.

    Args:
        program: Executable name, such as `clojure` or `ruff`.
        hint: How to install it, shown when it is missing.

    Returns:
        The resolved path.

    Raises:
        ToolMissing: The program is not on PATH.
    """
    found = shutil.which(program)
    if not found:
        raise ToolMissing(f"{program} is not on PATH{f'. {hint}' if hint else ''}")
    return found


def is_hosted():
    """Whether a Vis host is in the room to confine and own what we start.

    Returns:
        True inside a Vis process, False in a bare test run or an extension
        driven by hand.
    """
    return not hasattr(vis, "outside")


def shell_call():
    """The shell this process starts children with.

    Inside Vis that is `vis.jailed_shell` and nothing else: a refusal from it is
    the jail saying no, and retrying the same command unconfined would be
    exactly the escape the jail exists to prevent. Outside a Vis process — this
    repository's own test run, or an extension driven by hand — there is no host
    to enforce a jail and no session to confine to, so the local shell runs it.

    Returns:
        The callable that takes one shell options map.
    """
    return vis.jailed_shell if is_hosted() else vis.shell


def spawn(command, *, cwd=None, env=None, timeout_s=None, read_write=()):
    """Start one shell command as a confined child and answer its live handle.

    Args:
        command: The shell line to run.
        cwd: Directory to run in; the current directory when omitted.
        timeout_s: Seconds this call waits before answering. The child is not
            killed when the wait ends: it keeps running under the handle's id.
        env: Variables for this child, over the ones it inherits; a name mapped
            to None is unset.
        read_write: Paths outside the session's own roots this child may read
            and write, such as the directory holding its rendezvous.

    Returns:
        The shell handle: a mapping carrying `id`, `pid`, `status` and `exit`,
        with `logs`, `wait`, `type` and `stop` on it.
    """
    options = {"command": str(command)}
    if cwd:
        options["cwd"] = str(cwd)
    if env:
        options["env"] = dict(env)
    if timeout_s:
        options["timeout_secs"] = max(1, int(math.ceil(float(timeout_s))))
    grants = [str(path) for path in read_write]
    if grants:
        options["allow_read_write"] = grants
    return shell_call()(options)


def run_directory(name="run"):
    """A private directory for one run's streams, removed by its caller.

    Args:
        name: What the directory is for, used in its name.

    Returns:
        The created directory.
    """
    return Path(tempfile.mkdtemp(prefix=f"{RUN_PREFIX}{name}-"))


def run(command, *, cwd=None, timeout_s=300, stdin=None, env=None, read_write=()):
    """Run `command` to completion and capture what it printed.

    Args:
        command: Program and arguments.
        cwd: Directory to run in; the current directory when omitted.
        timeout_s: Seconds to wait before giving up.
        stdin: Text to write to the process, or None.
        env: Variables for this run, over the ones it inherits; a name mapped to
            None is unset.
        read_write: Paths outside the session's own roots this run may read and
            write, such as the dependency cache its toolchain fills. The private
            run directory is granted on top of these.

    Returns:
        A `ToolRun`, whatever the exit status.

    Raises:
        ToolMissing: The program is not installed.
        ToolTimeout: The deadline passed while it was still running.
    """
    argv = [str(part) for part in command]
    if os.sep not in argv[0]:
        tool_path(argv[0])
    work = run_directory("run")
    try:
        out_file, err_file = work / "out", work / "err"
        line = (
            f"{shlex.join(argv)} >{shlex.quote(str(out_file))}"
            f" 2>{shlex.quote(str(err_file))}"
        )
        if stdin is not None:
            in_file = work / "in"
            in_file.write_text(str(stdin), encoding="utf-8")
            line += f" <{shlex.quote(str(in_file))}"
        started = time.monotonic()
        handle = spawn(
            line,
            cwd=cwd,
            env=env,
            timeout_s=timeout_s,
            read_write=[work, *read_write],
        )
        # A spawn answers as soon as it has a handle; the wait is where a
        # command that is still running spends its budget.
        settled = (
            handle if handle.get("status") != "running" else handle.wait(timeout_s)
        )
        exit_code = settled.get("exit")
        if settled.get("status") != "exited" or exit_code is None:
            handle.stop()
            raise ToolTimeout(f"{argv[0]} did not finish within {timeout_s}s")
        elapsed = int((time.monotonic() - started) * 1000)
        out, err = _read(out_file), _read(err_file)
        if int(exit_code) == 127 and "not found" in err:
            raise ToolMissing(f"{argv[0]} is not on PATH")
        return ToolRun(tuple(argv), int(exit_code), out, err, elapsed)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _read(path):
    """What a run wrote to one of its stream files, empty when it wrote nothing."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
