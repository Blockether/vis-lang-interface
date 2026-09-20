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
