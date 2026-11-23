# vis-lang-interface

The shared contract for [Vis](https://github.com/Blockether/vis) language extensions. It gives
tools such as `clj.lint_code` and `py.lint_code` the same result types and Activity presentation.

## Install

Add the contract to your extension's `pyproject.toml`:

```toml
[project]
dependencies = [
  "vis-agent>=0.5.30",
  "vis-lang-interface @ git+https://github.com/Blockether/vis-lang-interface@v4.2.0",
]
```

## Use

Run the project's language tools and return the shared result types. This package supplies no
parser and registers no tools of its own.

| Module | Purpose |
| --- | --- |
| `results` | Return diagnostics and results for formatting, lint, syntax, tests, coverage, builds and REPLs. |
| `changes` | Count added and removed lines after formatting. |
| `process` | Start a language tool and collect its output. |
| `runtime` | Start a runtime that stays active between calls. |
| `project` | Find project roots and source files, and normalize list arguments. |
| `presentation` | Show language results in Vis Activity. |
| `syntax` | Check changed files with the language parser and repair them when safe. |
| `prompt` | Tell the model which tools to use and when to use them. |

For examples and API details, see the [language extension reference](docs/extension-reference.md).
For extensions that use this contract, see [vis-lang-clojure](https://github.com/Blockether/vis-lang-clojure)
and [vis-lang-python](https://github.com/Blockether/vis-lang-python).

## Development

```bash
vis-agent python -m pytest tests -q
```
