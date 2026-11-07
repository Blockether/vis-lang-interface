"""The routing block a language extension puts in the system prompt.

Vis prints one section per active extension into the system prompt. The model
must rediscover an extension that contributes no section before it uses it. It
then runs the toolchain by hand in a shell, and it never asks whether the REPL
that this session started is still alive. Nothing else says so, because Vis
keeps live resources out of the turn context on purpose. So this block is what
makes a runtime that outlives the call worth starting at all.

The text lives here, not in each extension, so that every language reads the
same way. The alias and its verbs come first, each with its real signature, so
the model calls a verb without a probe first. Then comes what to use instead of a
shell line, and then whatever is true only of that language.

    from vis_lang_interface import prompt

    PROMPT = prompt.routing(
        "Clojure",
        "clj",
        ("format_code", "lint_code", "run_tests", "repl_start", "repl_eval"),
        notes=("`clj.repl_eval` needs a REPL `clj.repl_start` already started.",),
        tools=ClojureTools,
    )
"""

from __future__ import annotations

import inspect
import re

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
"""Public tool verbs, in the order a block lists them; syntax checks are hooks only."""

_TOOLCHAIN = ("format_code", "lint_code", "run_tests", "build")
"""The verbs that run the toolchain once and answer a result."""

_REPL = ("repl_start", "repl_status", "repl_connect", "repl_eval", "repl_stop")
"""The verbs that own a runtime living between calls."""


_QUALIFIER = re.compile(r"\b(?:typing|collections\.abc)\.")
"""Module prefixes that a type name in the prompt does not need."""


def _type_name(annotation):
    """A return annotation as a short type name, without quotes or module prefixes."""
    text = (
        annotation
        if isinstance(annotation, str)
        else inspect.formatannotation(annotation)
    )
    return _QUALIFIER.sub("", text.strip("'\""))


def _signature(alias, verb, tools):
    """One verb as `alias.verb(arguments) -> Result`: defaults stay, annotations go."""
    method = getattr(tools, verb, None)
    if not callable(method):
        raise ValueError(f"{alias}.{verb} has no method on {tools!r}")
    signature = inspect.signature(method)
    parameters = list(signature.parameters.values())
    if parameters and parameters[0].name == "self":
        parameters = parameters[1:]
    bare = signature.replace(
        parameters=[p.replace(annotation=p.empty) for p in parameters],
        return_annotation=signature.empty,
    )
    result = signature.return_annotation
    returns = "" if result is signature.empty else f" -> {_type_name(result)}"
    return f"{alias}.{verb}{bare}{returns}"


def routing(language, alias, verbs=VERBS, *, notes=(), tools=None):
    """The block this extension contributes to the system prompt.

    Args:
        language: The language as a person names it, such as `"Clojure"`.
        alias: The extension's alias, which is also the symbol the verbs hang
            off in the sandbox, such as `"clj"` for `clj.run_tests`.
        verbs: The verbs this extension serves, named as in `VERBS`. They are
            listed in that order, whatever order they arrive in.
        notes: Extra lines for what is true only of this language. Examples are
            a verb that needs a live REPL and a lint that also reports
            reflection. Each one is a sentence of routing or policy. Do not
            repeat a signature: the verb lines already show it.
        tools: The class or object that serves the verbs. When given, each verb
            gets its own line with its real signature: defaults and the return
            type name stay, argument annotations, `self` and module prefixes go.
            Without it, the verbs are only named.

    Returns:
        The block, as text.

    Raises:
        ValueError: A verb is not one this contract knows, none was named, or
            `tools` has no method for a verb.
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
    if tools is None:
        lines.extend(f"  {' · '.join(row)}" for row in (toolchain, repl) if row)
    else:
        lines.extend(f"  {_signature(alias, verb, tools)}" for verb in chosen)
    if toolchain:
        lines.append(
            f"Use these verbs, not a shell command, to format, lint and test {language}."
            " Read their typed result; do not parse output."
        )
    if repl:
        lines.append(
            "A REPL stays alive after the call that started it, and nothing in the context"
            f" shows that it is alive. `{alias}.repl_status` tells you; `{alias}.repl_stop` ends"
            " it. Evaluate in a live REPL to check a change without a new toolchain startup."
        )
    lines.extend(text for text in (str(note).strip() for note in notes) if text)
    return "\n".join(lines)


__all__ = ["VERBS", "routing"]
