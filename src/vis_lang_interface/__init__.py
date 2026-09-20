"""The contract a Vis language extension answers with.

Vis knows nothing about programming languages. A language extension runs that
language's own toolchain — cljfmt and clj-kondo through the Clojure CLI, ruff
and pytest for Python — and hands the model back the results in this package's
shapes, so one presentation renders them all and a model that learned one
extension already knows the next.

Import what you need:

* `results` — the frozen result types every language tool returns.
* `process` — running a toolchain program and reading what it printed.
* `project` — finding the project directory and its source files.
* `presentation` — the Activity rendering the results share.
* `data` — exact JSON and TOML checks from the standard library.
"""

from vis_lang_interface.process import ToolMissing, ToolRun, ToolTimeout, run, tool_path
from vis_lang_interface.project import project_root, source_files
from vis_lang_interface.results import (
    Diagnostic,
    FormatResult,
    LintResult,
    ReplResult,
    ReplSession,
    TestFailure,
    TestResult,
)

__all__ = [
    "Diagnostic",
    "FormatResult",
    "LintResult",
    "ReplResult",
    "ReplSession",
    "TestFailure",
    "TestResult",
    "ToolMissing",
    "ToolRun",
    "ToolTimeout",
    "project_root",
    "run",
    "source_files",
    "tool_path",
]
