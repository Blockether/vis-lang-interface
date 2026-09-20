"""Running a language toolchain as a child process.

An extension runs with your own permissions, so these helpers stay deliberately
narrow: one command, one timeout, captured output, and an error that names the
missing program instead of a bare exit code.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Annotated


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


def run(command, *, cwd=None, timeout_s=300, stdin=None, env=None):
    """Run `command` to completion and capture what it printed.

    Args:
        command: Program and arguments.
        cwd: Directory to run in; the current directory when omitted.
        timeout_s: Seconds to wait before giving up.
        stdin: Text to write to the process, or None.
        env: Complete environment for the child, or None to inherit.

    Returns:
        A `ToolRun`, whatever the exit status.

    Raises:
        ToolMissing: The program is not installed.
        ToolTimeout: The deadline passed while it was still running.
    """
    argv = [str(part) for part in command]
    started = time.monotonic()
    try:
        done = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolMissing(f"{argv[0]} is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolTimeout(f"{argv[0]} did not finish within {timeout_s}s") from exc
    elapsed = int((time.monotonic() - started) * 1000)
    return ToolRun(
        tuple(argv), done.returncode, done.stdout or "", done.stderr or "", elapsed
    )
