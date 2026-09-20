# vis-lang-interface

The public language surface for [Vis](https://github.com/Blockether/vis): the extension that
publishes `format_code`, `lint_code`, `run_tests`, `repl_start`, `repl_eval`, `repl_status`,
`repl_stop` and `connect_repl`, and the registrar every language pack hooks into.

Vis itself knows no language. It loads this extension; this extension loads the packs it finds
and dispatches each call to the pack that claims the language.

## What lives here

- **Registrar** — a pack declares itself with `META-INF/vis-lang/pack.edn` or registers
  programmatically; this library validates it and publishes its handlers.
- **REPL interface** — the session lifecycle every managed REPL follows, whatever language runs it.
- **Balance interface** — the delimiter-repair hook the write gate spends before a patch lands.
- **Prompt** — the capability block that tells a model which packs are active.
- **Shared utilities** — verdict documents, workspace detection, output limits, activity presentation.

## Packs

- [vis-lang-python](https://github.com/Blockether/vis-lang-python)
- [vis-lang-clojure](https://github.com/Blockether/vis-lang-clojure)

## Status

Early: extraction from the Vis engine is in progress. Until the first release, pin by commit.
