"""Running a language toolchain as a child process.

Everything a language extension starts goes through `vis.jailed_shell`. So the
confinement that the person running Vis turned on covers the toolchain as much
as the model's own shell. A jailed toolchain still reaches the package indexes
it needs. Maven, Clojars and PyPI answer through the egress proxy.

These helpers stay deliberately narrow: one command, one timeout, captured
output, and an error that names the missing program instead of a bare exit code.

A shell child runs under a pty, with stdout and stderr merged into one
normalized stream. Tool output is data, such as JSON from ruff and EDN from
clj-kondo. So nothing here reads that stream. The command writes its own streams
into a private run directory granted to that one child. The files are read back
when it is done.
"""

from __future__ import annotations

import hashlib
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


@dataclass(frozen=True)
class VisPython:
    """The Python of the Vis that hosts this process, and how to run it.

    Vis can be a command on PATH, a native binary in a container or a JVM from a
    source checkout. So a language extension asks `vis_python()` and never
    searches PATH for `vis-agent` or computes the Vis home.
    """

    launcher: Annotated[
        tuple[str, ...],
        "Command that runs this Vis from any directory. Empty without a Vis.",
    ]
    shared_packages: Annotated[Path, "Directory of the Vis shared packages."]

    @property
    def is_available(self):
        """Whether a Vis is there to run Python and uv."""
        return bool(self.launcher)

    def python(self, *args, shared=False):
        """The command that runs Vis Python with `args`, like `vis-agent python`.

        Args:
            *args: Arguments for Python.
            shared: Use the Vis shared packages and not the project's `.venv`,
                like `vis-agent python --shared`.

        Returns:
            The command as a list.

        Raises:
            ToolMissing: This process has no Vis.
        """
        if not self.launcher:
            raise ToolMissing("vis-agent is not on PATH. Install vis-agent.")
        mode = ("--shared",) if shared else ()
        return [*self.launcher, "python", *mode, *args]

    def uv(self, *args, shared=False):
        """The command that runs the uv of Vis with `args`, like `vis-agent python uv`.

        Args:
            *args: Arguments for uv.
            shared: Install to the Vis shared packages.

        Returns:
            The command as a list.

        Raises:
            ToolMissing: This process has no Vis.
        """
        return self.python("uv", *args, shared=shared)


def vis_python():
    """The Python of the Vis that hosts this process: `vis.python_runtime()`.

    A Vis host older than `vis.python_runtime` names no location. There, the
    launcher is `vis-agent` on PATH, and the shared packages follow
    `VIS_PYTHON_PACKAGES`, then `VIS_HOME`, then `~/.vis`.

    Returns:
        The launcher and the shared packages. The launcher is empty without a Vis.
    """
    read = getattr(vis, "python_runtime", None)
    if read:
        found = read()
        return VisPython(tuple(found.launcher), Path(found.shared_packages))
    agent = shutil.which("vis-agent")
    packages = os.environ.get("VIS_PYTHON_PACKAGES", "").strip()
    if not packages:
        home = os.environ.get("VIS_HOME", "").strip() or os.path.join("~", ".vis")
        packages = os.path.join(home, "python", "packages")
    return VisPython((agent,) if agent else (), Path(packages).expanduser())


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

    Inside Vis, that is `vis.jailed_shell` and nothing else. A refusal from it
    is the jail saying no. Retrying the same command without confinement would
    be exactly the escape that the jail exists to prevent.

    Outside a Vis process, there is no host to enforce a jail and no session to
    confine to. Examples are this repository's own test run and an extension
    driven by hand. There, the local shell runs the command.

    Returns:
        The callable that takes one shell options map.
    """
    return vis.jailed_shell if is_hosted() else vis.shell


def attach_shell(shell_id):
    """Get the live shell without starting a child under this id."""
    if hasattr(vis, "ShellFuture"):
        return shell_call()({"op": "attach", "id": shell_id})
    return shell_call()({"op": "logs", "id": shell_id, "offset": -1})


def call_env():
    """Variables that a `before` op hook added to this tool call with `vis.with_env`.

    A name mapped to None is unset for the child. `run` gives these to its child,
    which ends inside the call. A child that outlives the call, such as a REPL,
    gets them only when its caller passes them to `spawn`: a shared runtime must
    not keep one call's variables for every later call. A Vis host older than
    `vis.call_env` cannot run such a hook, so no hook added any variables there.

    Returns:
        A new `{name: value or None}` map, empty when no hook added variables.
    """
    read = getattr(vis, "call_env", None)
    added = read() if read else None
    return {
        str(name): None if value is None else str(value)
        for name, value in (added or {}).items()
    }


def env_fingerprint(values):
    """`{name: digest}` for one environment delta: its shape without its values.

    A status, a log and a refusal can show it, because no value appears in it. A
    name set to None fingerprints as `unset`. The digest is the first 12 hex
    characters of SHA-256, as the Clojure library makes it.

    Args:
        values: A `{name: value or None}` map, such as `call_env()`.

    Returns:
        The fingerprint, sorted by name.
    """
    return {
        str(name): "unset"
        if value is None
        else hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
        for name, value in sorted((values or {}).items())
    }


def spawn(command, *, cwd=None, env=None, timeout_s=None, read_write=(), shell_id=None):
    """Start one shell command as a confined child and answer its live handle.

    Args:
        command: The shell line to run.
        cwd: Directory to run in, or the current directory when omitted.
        timeout_s: Seconds this call waits before answering. The child is not
            killed when the wait ends. It keeps running under the handle's id.
        env: Variables for this child, over the ones it inherits. A name mapped
            to None is unset.
        read_write: Paths outside the session's own roots this child may read
            and write, such as the directory holding its rendezvous.
        shell_id: Id for the shell. The same id, command and directory reach
            the same live child from a later process. None lets the host pick.

    Returns:
        A shell Future with `logs` and `type`. An older Vis host gives a
        legacy shell handle.
    """
    options: dict[str, object] = {"command": str(command)}
    if cwd:
        options["cwd"] = str(cwd)
    if env:
        options["env"] = dict(env)
    if timeout_s:
        options["timeout_secs"] = max(1, int(math.ceil(float(timeout_s))))
    grants = [str(path) for path in read_write]
    if grants:
        options["allow_read_write"] = grants
    if shell_id:
        options["id"] = str(shell_id)
    return shell_call()(options)


def _shell_result(handle, timeout_s):
    """Wait for the child without stopping it if the deadline passes."""
    result = getattr(handle, "result", None)
    if result is not None:
        return result(timeout=timeout_s)
    # Released extensions can still run on a host with the old handle API.
    return handle.wait(timeout_s) if handle.get("status") == "running" else handle


def _cancel_shell(handle):
    """Stop the child owned by this handle."""
    cancel = getattr(handle, "cancel", None)
    return cancel() if cancel is not None else handle.stop()


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
        cwd: Directory to run in, or the current directory when omitted.
        timeout_s: Seconds to wait before giving up.
        stdin: Text to write to the process, or None.
        env: Variables for this run, over the ones it inherits and over the
            ones an op hook added to this call (`call_env`). A name mapped to
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
            env={**call_env(), **dict(env or {})},
            timeout_s=timeout_s,
            read_write=[work, *read_write],
        )
        try:
            settled = _shell_result(handle, timeout_s)
            exit_code = settled.get("exit")
            if settled.get("status") != "exited" or exit_code is None:
                raise TimeoutError
        except TimeoutError:
            _cancel_shell(handle)
            raise ToolTimeout(f"{argv[0]} did not finish within {timeout_s}s") from None
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
