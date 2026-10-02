# vis-lang-interface

This Python-only repository is the contract that every Vis language extension returns. Vis itself
has no language contract and must never get one.

- `src/vis_lang_interface/` is a library that other extensions import as a Git dependency. `extension.py` registers the contract with Vis and serves no tools.
- Result types are frozen dataclasses with `Annotated` fields. A new field is a version bump for every extension that returns it. A renamed field breaks them, so rename only on purpose.
- Give every exported method an explicit Activity presentation with a capitalized English label. Use `show_start=False` for quick local reads. Test the success, failure and empty states.
- Format and lint with ruff. Run the pytest tests from the repository root: `vis-agent python -m pytest tests -q`.
- Do not add Clojure, a JVM, tree-sitter or a parser of our own. A verdict comes from the parser that the language already ships.
