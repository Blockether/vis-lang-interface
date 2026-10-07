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
  "vis-lang-interface @ git+https://github.com/Blockether/vis-lang-interface@v2.6.0",
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
| `vis_lang_interface.project` | `project_root`, `source_files`, `string_list` — a list argument that arrived as one bare string becomes one entry, not one entry for each character |
| `vis_lang_interface.presentation` | Activity rendering every language binding shares: a pass or fail verdict for lint, syntax and test runs, changed-line counts for formatting, and an evaluation's code, repairs, output, error and value |
| `vis_lang_interface.syntax` | `SyntaxGuard` — validates edit previews, applies language repairs and reports files that remain unparseable |
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

`SyntaxGuard` asks the language's own parser whether changed files still parse. Syntax checks run
only through edit hooks. They are not tools available to `python_execution` or public routing verbs.

The interface has no parser. Supply the file suffixes and a private `_check_syntax` callback.
The callback takes `{path: text}` and the workspace root. It returns a `SyntaxResult` whose
diagnostics name the supplied paths. Keep the callback outside the extension's exported symbols.

```python
from vis_lang_interface import Diagnostic, SyntaxResult
from vis_lang_interface.syntax import SyntaxGuard

def _check_syntax(sources, root):
    rows = [Diagnostic(path, line, column, "error", message) for ... in parse(sources)]
    return SyntaxResult.of("clojure", rows, files=len(sources))

guard = SyntaxGuard("clojure", (".clj", ".cljs", ".cljc", ".edn"), _check_syntax)

vis.register_extension(vis.Extension(..., op_hooks=guard.op_hooks(), ctx=guard.ctx))
```

- Before a `patch` writes, Vis gives the hook the proposed text and changed line spans.
  If a repair callback returns valid source, the host writes that source once and reports the corrections.
  Otherwise, a patch that breaks a parseable file is refused. A previously broken file can still be repaired in steps.
- After a patch, the guard checks the changed file again.
  After a Python block, it can repair changed files before checking them again.
  This includes writes from `Path.write_text()`, `open(..., "w")` and programs started by the block.
- Unresolved errors appear in `session["clojure_syntax_errors"]`.
  Completed repairs appear in `session["clojure_syntax_repairs"]`, with notes and diffs.
  Other language names replace the `clojure` prefix.
- A patch is atomic for one file. A Python block is not transactional.
  Post-block repairs happen after the original writes and cannot undo the block's other effects.
  Each repair checks that the file still matches before replacing it. Symbolic links are not replaced.
- The guard watches tracked and untracked workspace files, but skips ignored files.
  If Git cannot list files, it walks the workspace and skips hidden and build directories.
  Between listings, file and directory stat calls find changes without a process.
- If the parser is unavailable, the guard allows the operation, logs the failure and waits two minutes before retrying.
  It never accepts a repair without successful validation.

To enable repairs, pass `repair=repair_source` to `SyntaxGuard`.
The callback receives the proposed `source` and keyword arguments `original`, `spans` and `parses_clean`.
Spans are inclusive, one-based line ranges in the proposed text.
After a Python block, `original` is `None` and the spans cover the whole file.

Return an object with a changed `source` string and a nonempty list or tuple of `notes`.
Return `None` when the repair is unsafe or cannot produce valid source.
Use `parses_clean(candidate)` to validate the complete candidate without executing it.
Keep language parsing and repair algorithms in the language extension, not this package.

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
