"""The contract a Vis language extension answers with.

Vis knows nothing about programming languages. A language extension runs that
language's own toolchain — cljfmt and clj-kondo through the Clojure CLI, ruff
and pytest for Python — and hands the model back the results in this package's
shapes, so one presentation renders them all and a model that learned one
extension already knows the next.

Every process an extension starts goes through the workspace jail, whether it is
one run of a formatter or a runtime that stays alive between calls.

Import what you need:

* `results` — the frozen result types every language tool returns.
* `process` — running a toolchain program and reading what it printed.
* `runtime` — a language runtime that outlives the call that started it.
* `project` — finding the project directory and its source files.
* `presentation` — the Activity rendering the results share.
"""

from vis_lang_interface.process import (
    ToolMissing,
    ToolRun,
    ToolTimeout,
    run,
    spawn,
    tool_path,
)
from vis_lang_interface.project import project_root, source_files
from vis_lang_interface.results import (
    BuildArtifact,
    BuildResult,
    Diagnostic,
    FormatResult,
    LintResult,
    ReplResult,
    ReplSession,
    TestFailure,
    TestResult,
)
from vis_lang_interface.runtime import Rendezvous, Runtime, RuntimeGone

__all__ = [
    "BuildArtifact",
    "BuildResult",
    "Diagnostic",
    "FormatResult",
    "LintResult",
    "Rendezvous",
    "ReplResult",
    "ReplSession",
    "Runtime",
    "RuntimeGone",
    "TestFailure",
    "TestResult",
    "ToolMissing",
    "ToolRun",
    "ToolTimeout",
    "project_root",
    "run",
    "source_files",
    "spawn",
    "tool_path",
]
