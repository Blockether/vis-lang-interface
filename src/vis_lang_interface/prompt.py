"""The routing block a language extension puts in the system prompt.

Vis prints one section per active extension into the system prompt. The model must
rediscover an extension that contributes no section before it uses it. It then runs the
toolchain by hand in a shell, and it never asks whether the REPL that this session
started is still alive. Nothing else says so, because Vis keeps live resources out of
the turn context on purpose. So this block is what makes a runtime that outlives the
call worth starting at all.

The text lives here, not in each extension, so that every language reads the same way.
The alias and its verbs come first. Then comes what to use instead of a shell line, and
then whatever is true only of that language.

    from vis_lang_interface import prompt

    PROMPT = prompt.routing(
        "Clojure",
        "clj",
        ("format_code", "lint_code", "run_tests", "repl_start", "repl_eval"),
        notes=("`clj.repl_eval` needs a REPL `clj.repl_start` already started.",),
    )
"""

from __future__ import annotations

VERBS = (
    "format_code",
    "lint_code",
    "run_tests",
    "build",
    "repl_start",
    "repl_status",
    "repl_connect",
    "repl_eval",
    "repl_stop",
)
"""Every verb this contract knows, in the order a block lists them."""

_TOOLCHAIN = ("format_code", "lint_code", "run_tests", "build")
"""The verbs that run the toolchain once and answer a result."""

_REPL = ("repl_start", "repl_status", "repl_connect", "repl_eval", "repl_stop")
"""The verbs that own a runtime living between calls."""


def routing(language, alias, verbs=VERBS, *, notes=()):
    """The block this extension contributes to the system prompt.

    Args:
        language: The language as a person names it, such as `"Clojure"`.
        alias: The extension's alias, which is also the symbol the verbs hang
            off in the sandbox, such as `"clj"` for `clj.run_tests`.
        verbs: The verbs this extension serves, named as in `VERBS`. They are
            listed in that order, whatever order they arrive in.
        notes: Extra lines for what is true only of this language. Examples are
            a verb that needs a live REPL and a lint that also reports reflection.
            Each one is a sentence of routing or policy, never a signature. The
            method's own docstring already carries its arguments and result.

    Returns:
        The block, as text.

    Raises:
        ValueError: A verb is not one this contract knows, or none was named.
    """
    named = tuple(dict.fromkeys(str(verb) for verb in verbs))
    unknown = [verb for verb in named if verb not in VERBS]
    if unknown:
        raise ValueError(f"unknown language verbs: {', '.join(sorted(unknown))}")
    chosen = [verb for verb in VERBS if verb in named]
    if not chosen:
        raise ValueError("a language extension contributes at least one verb")

    toolchain = [f"{alias}.{verb}" for verb in chosen if verb in _TOOLCHAIN]
    repl = [f"{alias}.{verb}" for verb in chosen if verb in _REPL]

    lines = [f"{alias} surface active — {language} through its own toolchain:"]
    lines.extend(f"  {' · '.join(row)}" for row in (toolchain, repl) if row)
    if toolchain:
        lines.append(
            f"These verbs are the {language} toolchain here: reach for them instead of a shell"
            " line that runs the formatter, the linter or the test command, and read the typed"
            " result they answer rather than parsing output."
        )
    if repl:
        lines.append(
            "A REPL outlives the call that started it and nothing reprints that it is alive:"
            f" `{alias}.repl_status` is what says so, `{alias}.repl_stop` is what ends it."
            " Evaluating in a live one is how you check a change without paying the"
            " toolchain's startup again."
        )
    lines.extend(text for text in (str(note).strip() for note in notes) if text)
    return "\n".join(lines)


__all__ = ["VERBS", "routing"]
