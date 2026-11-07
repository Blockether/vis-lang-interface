"""The routing block every language extension contributes reads the same way."""

import collections.abc
import typing
from typing import Annotated

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


def test_syntax_checks_are_private_hooks_not_public_toolchain_verbs():
    assert "check_syntax" not in prompt.VERBS
    assert "check_syntax" not in prompt.routing("Clojure", "clj")
    with pytest.raises(ValueError, match="unknown language verbs: check_syntax"):
        prompt.routing("Clojure", "clj", ("check_syntax",))


def test_a_toolchain_verb_routes_away_from_a_shell_line():
    block = prompt.routing("Python", "py", ("run_tests",))
    assert "not a shell command" in block
    assert "repl_status" not in block


def test_a_repl_verb_says_a_live_runtime_is_reported_nowhere_else():
    block = prompt.routing("Clojure", "clj", ("repl_start", "repl_status", "repl_stop"))
    assert "nothing in the context" in block
    assert "`clj.repl_status` tells you" in block
    assert "not a shell command" not in block


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


class TestResult:
    """A result type, named in a return annotation as text."""


class _Tools:
    def run_tests(
        self,
        paths: Annotated[collections.abc.Sequence[str], "Test files."] = (),
        *,
        keyword: Annotated[str, "pytest's -k selection."] = "",
        timeout_s: int = 900,
    ) -> "TestResult":
        """Run the tests."""
        raise NotImplementedError

    def repl_eval(self, code: str, *, cwd: str = "") -> typing.Optional[str]:
        """Evaluate code."""
        raise NotImplementedError

    def repl_status(self, cwd: str = "") -> collections.abc.Sequence[str]:
        """Report the REPL."""
        raise NotImplementedError


def test_tools_give_each_verb_its_callable_signature_in_contract_order():
    block = prompt.routing(
        "Python", "py", ("repl_status", "repl_eval", "run_tests"), tools=_Tools()
    )
    assert block.splitlines()[1:4] == [
        "  py.run_tests(paths=(), *, keyword='', timeout_s=900) -> TestResult",
        "  py.repl_status(cwd='') -> Sequence[str]",
        "  py.repl_eval(code, *, cwd='') -> Optional[str]",
    ]


def test_a_verb_that_the_tools_do_not_serve_is_refused():
    with pytest.raises(ValueError, match="py.lint_code has no method"):
        prompt.routing("Python", "py", ("run_tests", "lint_code"), tools=_Tools)


def test_coverage_is_part_of_the_test_run_not_a_verb():
    assert "coverage" not in prompt.VERBS
    with pytest.raises(ValueError):
        prompt.routing("Clojure", "clj", ("coverage", "run_tests"))
