# vis-lang-interface

Python only. This repository is the contract every Vis language extension answers with; Vis
itself has no language contract and must never gain one.

- `src/vis_lang_interface/` is a library other extensions import as a Git dependency, and
  `extension.py` registers that contract with Vis; it serves no tools of its own.
- Result types are frozen dataclasses with `Annotated` fields. Adding a field is a version bump
  for every extension that returns it; renaming one breaks them, so change names deliberately.
- Every exported method owns an explicit Activity presentation with a capitalized English label.
  Quick local reads use `show_start=False`. Cover success, failure and empty states in tests.
- Formatting and lint are ruff. Tests are pytest:
  `vis-agent python -m pytest tests -q` from the repository root.
- No Clojure, no JVM, no tree-sitter and no parser of our own: a verdict comes from the parser
  the language already ships.
