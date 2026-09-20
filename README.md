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
  "vis-lang-interface @ git+https://github.com/Blockether/vis-lang-interface@v1.0.1",
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
| `vis_lang_interface.process` | `run`, `tool_path`, `ToolRun`, `ToolMissing`, `ToolTimeout` |
| `vis_lang_interface.project` | `project_root`, `source_files` |
| `vis_lang_interface.presentation` | Activity rendering every language binding shares |

## The extensions that use it

- [vis-lang-clojure](https://github.com/Blockether/vis-lang-clojure) — cljfmt, zprint, clj-kondo,
  Lazytest and an nREPL, through the `clojure` CLI.
- [vis-lang-python](https://github.com/Blockether/vis-lang-python) — ruff, pytest and a managed
  project REPL.

## Development

```bash
vis-agent python -m pytest tests -q
```
