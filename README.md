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
  "vis-agent>=0.2.26",
  "vis-lang-interface @ git+https://github.com/Blockether/vis-lang-interface@v2.4.0",
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
| `vis_lang_interface.results` | `Diagnostic`, `FormatResult`, `LintResult`, `SyntaxResult`, `TestResult`, `TestFailure`, `BuildResult`, `BuildArtifact`, `ReplResult`, `ReplSession` |
| `vis_lang_interface.changes` | `line_changes` — the lines an edit added and removed, as `git diff --minimal --numstat` counts them |
| `vis_lang_interface.process` | `run`, `spawn`, `tool_path`, `ToolRun`, `ToolMissing`, `ToolTimeout` |
| `vis_lang_interface.runtime` | `start`, `Runtime`, `Rendezvous`, `RuntimeGone` — a runtime that stays alive between calls |
| `vis_lang_interface.project` | `project_root`, `source_files` |
| `vis_lang_interface.presentation` | Activity rendering every language binding shares: a pass or fail verdict for lint, syntax and test runs, changed-line counts for formatting, and an evaluation's code, output, error and value |
| `vis_lang_interface.syntax` | `SyntaxGuard` — refuses a patch that makes a file unparseable and reports Python writes that did |
| `vis_lang_interface.prompt` | `routing` — the block that tells the model your verbs exist |

## Count what formatting changed

`FormatResult.lines_added` and `lines_removed` say how much formatting changed. Count them with
`line_changes`, so every extension reports the numbers `git diff --minimal --numstat` gives:

```python
from vis_lang_interface import FormatResult, line_changes

added, removed = line_changes(before, formatted)
result = FormatResult(
    "python", (path,), (), is_written=True, lines_added=added, lines_removed=removed
)
```

A line counts with its newline: a changed line counts once as removed and once as added, and a last
line that only gains or loses its newline counts as changed. A source file of a few thousand lines
takes about a millisecond. A changed region of tens of thousands of lines that exact counting cannot
settle in about half a second is matched through the lines that repeat least; its counts can then
exceed the fewest, never fall below them.

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

## Keep source files parseable

`SyntaxGuard` asks the language's own parser whether the files the model changes still parse. The
interface has no parser: give the guard the file suffixes your parser reads and a `check` function.
`check` takes `{path: text}` and the workspace root and returns a `SyntaxResult` whose diagnostics
name the paths it was given.

```python
from vis_lang_interface import Diagnostic, SyntaxResult
from vis_lang_interface.syntax import SyntaxGuard

def check(sources, root):
    rows = [Diagnostic(path, line, column, "error", message) for ... in parse(sources)]
    return SyntaxResult.of("clojure", rows, files=len(sources))

guard = SyntaxGuard("clojure", (".clj", ".cljs", ".cljc", ".edn"), check)

vis.register_extension(vis.Extension(..., op_hooks=guard.op_hooks(), ctx=guard.ctx))
```

- Before a `patch` writes, Vis gives the hook the file as the patch would leave it. A patch that
  would make a parseable file unparseable is refused, and nothing is written. A file that did not
  parse before is not guarded, so a repair can take several steps.
- After a `patch`, and after every `python_execution` block, the guard parses the changed files
  again. This covers `Path.write_text()`, `open(..., "w")` and the programs a block ran. Files that
  still do not parse reach the model's next request as `session["clojure_syntax_errors"]`.
- `patch` is atomic for one file, and the guard judges each call on its own. A block that patches
  several files keeps the patches that passed when a later one is refused.
- The guard watches the files under the workspace root that git lists, tracked or untracked but not
  ignored. Where git cannot list the tree, it walks it and skips hidden and build directories.
  Between listings, file and directory stat calls find what changed, so a block pays no process.
- When the parser cannot answer because its toolchain is missing, slow or failing, the guard allows
  the operation, logs why and does not ask again for two minutes.

A Vis host that predates the patch preview gives the before hook nothing to judge. There, the guard
only reports a broken file after the write.

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
