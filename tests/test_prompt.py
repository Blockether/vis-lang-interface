"""The routing block every language extension contributes reads the same way."""

import pytest

from vis_lang_interface import prompt


def test_the_block_leads_with_the_alias_and_its_verbs():
    block = prompt.routing("Clojure", "clj", ("run_tests", "format_code"))
    assert (
        block.splitlines()[0]
        == "clj surface active — Clojure through its own toolchain:"
    )
    assert block.splitlines()[1] == "  clj.format_code · clj.run_tests"


def test_verbs_are_listed_in_contract_order_whatever_order_they_arrive_in():
    block = prompt.routing("Python", "py", ("repl_eval", "repl_start", "lint_code"))
    assert block.splitlines()[1] == "  py.lint_code"
    assert block.splitlines()[2] == "  py.repl_start · py.repl_eval"


def test_a_toolchain_verb_routes_away_from_a_shell_line():
    block = prompt.routing("Python", "py", ("run_tests",))
    assert "instead of a shell line" in block
    assert "repl_status" not in block


def test_a_repl_verb_says_a_live_runtime_is_reported_nowhere_else():
    block = prompt.routing("Clojure", "clj", ("repl_start", "repl_status", "repl_stop"))
    assert "nothing reprints that it is alive" in block
    assert "`clj.repl_status` is what says so" in block
    assert "instead of a shell line" not in block


def test_notes_are_appended_as_their_own_lines():
    block = prompt.routing(
        "Clojure",
        "clj",
        ("run_tests",),
        notes=("`clj.run_tests` reuses a live REPL.", "  ", ""),
    )
    assert block.splitlines()[-1] == "`clj.run_tests` reuses a live REPL."


def test_an_unknown_verb_is_refused():
    with pytest.raises(ValueError, match="unknown language verbs: repl_restart"):
        prompt.routing("Clojure", "clj", ("run_tests", "repl_restart"))


def test_an_extension_that_serves_nothing_is_refused():
    with pytest.raises(ValueError, match="at least one verb"):
        prompt.routing("Clojure", "clj", ())
