# vis-lang-interface

The shared contract for [Vis](https://github.com/Blockether/vis) language extensions, written in
Python.

Vis knows nothing about programming languages. A language extension runs that language's own
toolchain and hands the model back a result; this package is what those results look like, so
`clj.lint_code` and `py.lint_code` read the same way and one presentation renders both.

## Building a language extension on it

Add the package as a dependency of your extension and return its result types:

```toml
dependencies = [
  "vis-agent>=0.2.10",
  "vis-lang-interface @ git+https://github.com/Blockether/vis-lang-interface@v2.0.0",
]
```

```python
from vis_lang_interface import LintResult, process

def lint(paths):
    done = process.run(["ruff", "check", "--output-format=json", *paths])
    return LintResult.of("python", findings_of(done.out), files=len(paths))
```

| Module | What it gives you |
| --- | --- |
| `vis_lang_interface.results` | `Diagnostic`, `FormatResult`, `LintResult`, `TestResult`, `TestFailure`, `BuildResult`, `BuildArtifact`, `ReplResult`, `ReplSession` |
| `vis_lang_interface.process` | `run`, `spawn`, `tool_path`, `ToolRun`, `ToolMissing`, `ToolTimeout` |
| `vis_lang_interface.runtime` | `start`, `Runtime`, `Rendezvous`, `RuntimeGone` — a runtime that stays alive between calls |
| `vis_lang_interface.project` | `project_root`, `source_files` |
| `vis_lang_interface.presentation` | Activity rendering every language binding shares |
| `vis_lang_interface.prompt` | `routing` — the block that tells the model your verbs exist |

## Tell the model your verbs exist

Vis prints one section per active extension into the system prompt. An extension that contributes
none still works, but the model has to discover it first, so it reaches for a shell line it already
knows and never asks whether the REPL this session started is still running — nothing else reports
that. `prompt.routing` writes that section for you:

```python
from vis_lang_interface import prompt

PROMPT = prompt.routing(
    "Python",
    "py",
    ("format_code", "lint_code", "run_tests", "repl_start", "repl_eval", "repl_stop"),
    notes=("`py.repl_eval` needs the REPL `py.repl_start` already started.",),
)

vis.register_extension(vis.Extension(..., alias="py", prompt=PROMPT))
```

Keep `notes` to routing and policy — when a verb is the right approach and what it refuses. Each
method's own docstring already carries its arguments and its result.

## Everything a language tool starts runs in the jail

`process.run` and `runtime.start` spawn through `vis.jailed_shell`, so whatever confinement the
person running Vis turned on covers the toolchain as much as the model's own shell. A jailed
toolchain still reaches the package indexes it needs: Maven, Clojars and PyPI answer through the
egress proxy.

A shell child runs under a pty, which merges stdout with stderr and normalizes what passes through.
Tool output is data, so `process.run` gives each run a private directory, writes the two streams
into files there and reads them back — `ToolRun.out` stays parseable JSON. A runtime that stays
alive between calls gets a rendezvous instead: two FIFOs in a private directory, handed to that one
child as its stdin and stdout, so it keeps speaking one JSON request per line in and one answer per
line out without ever touching the pty.

```python
from vis_lang_interface import runtime

live = runtime.start(["python3", driver_path], cwd=project)
answer = live.request({"op": "eval", "code": "1 + 1"}, timeout_s=30)
live.stop()
```

## The extensions that use it

- [vis-lang-clojure](https://github.com/Blockether/vis-lang-clojure) — cljfmt, zprint, clj-kondo,
  Lazytest and an nREPL, through the `clojure` CLI.
- [vis-lang-python](https://github.com/Blockether/vis-lang-python) — ruff, pytest and a managed
  project REPL.

## Development

```bash
vis-agent python -m pytest tests -q
```
