"""A syntax guard refuses breaking patches and reports writes that broke parsing."""

import os
import runpy
import shutil
from pathlib import Path

import blockether.vis.extension as vis
import pytest

from vis_lang_interface import Diagnostic, SyntaxResult, process, syntax
from vis_lang_interface.syntax import SyntaxGuard


class Parser:
    """A stand-in parser: a source parses when its parentheses balance."""

    def __init__(self):
        self.calls = []
        self.error = None

    def __call__(self, sources, root):
        self.calls.append((dict(sources), Path(root)))
        if self.error:
            raise self.error
        rows = [
            Diagnostic(path, text.count("\n") + 1, 1, "error", "EOF while reading")
            for path, text in sorted(sources.items())
            if text.count("(") != text.count(")")
        ]
        return SyntaxResult.of("lisp", rows, files=len(sources))


@pytest.fixture
def parser():
    return Parser()


@pytest.fixture
def guard(tmp_path, parser):
    return SyntaxGuard(
        "lisp", (".lisp", ".EDN"), parser, workspace_root=lambda: tmp_path, state={}
    )


def patched(before, after, path="src/core.lisp"):
    """The call a before hook receives for a patch, with its preview."""
    return {
        "op": "patch",
        "args": [path, []],
        "preview": {"path": path, "before": before, "after": after},
    }


def written(root, name, text):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def block():
    return {"op": "python_execution", "args": [{"code": "..."}], "result": {}}


def test_a_patch_that_breaks_a_parseable_file_is_refused(guard):
    refusal = guard.before_patch(patched("(a)\n", "(a\n"))
    assert refusal["marker"] == "block"
    assert refusal["reason"].startswith("src/core.lisp:2:1: EOF while reading.")
    assert "nothing was written" in refusal["reason"]
    assert "patch again" in refusal.get("hint", refusal["reason"])


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("(a)", "(b)"),
        ("(a", "(b"),
        ("(a", "(a)"),
        ("(a)", "(a)"),
    ],
    ids=["stays-clean", "stays-broken", "repairs", "unchanged"],
)
def test_a_patch_that_keeps_or_restores_parsing_is_allowed(guard, before, after):
    assert guard.before_patch(patched(before, after)) is None


def test_a_file_the_parser_does_not_read_is_never_parsed(guard, parser):
    assert guard.before_patch(patched("(a)", "(a", path="notes.md")) is None
    assert parser.calls == []


def test_suffixes_match_in_any_case(guard):
    assert guard.covers("deps.edn") and guard.covers("SRC/CORE.LISP")
    assert not guard.covers("core.lisp.orig")


def test_a_patch_without_a_usable_preview_is_allowed(guard, parser):
    assert guard.before_patch({"op": "patch", "args": ["src/core.lisp", []]}) is None
    assert guard.before_patch({"op": "patch", "preview": {"path": "a.lisp"}}) is None
    assert parser.calls == []


def test_a_failing_parser_allows_the_patch_and_rests(guard, parser):
    parser.error = RuntimeError("clojure is not installed")
    assert guard.before_patch(patched("(a)", "(a")) is None
    assert guard.before_patch(patched("(a)", "(b")) is None
    assert len(parser.calls) == 1


def test_a_patched_file_that_still_does_not_parse_is_reported(guard, tmp_path):
    written(tmp_path, "src/core.lisp", "(ns core\n")
    call = {"op": "patch", "args": ["src/core.lisp", []], "result": "patched"}
    guard.after_edit(call)
    assert guard.ctx() == {
        "lisp_syntax_errors": ["src/core.lisp:2:1: EOF while reading"]
    }
    written(tmp_path, "src/core.lisp", "(ns core)\n")
    guard.after_edit(call)
    assert guard.ctx() == {}


def test_a_refused_patch_is_not_parsed_again(guard, parser, tmp_path):
    written(tmp_path, "src/core.lisp", "(a")
    guard.after_edit({"op": "patch", "args": ["src/core.lisp", []], "result": None})
    assert parser.calls == []
    assert guard.ctx() == {}


def test_a_python_block_that_writes_files_is_checked(guard, parser, tmp_path):
    existing = written(tmp_path, "src/core.lisp", "(ns core)\n")
    written(tmp_path, "README.md", "# notes\n")
    guard.before_block(block())
    existing.write_text("(ns core\n  (:require [a]))\n(defn f [", encoding="utf-8")
    created = written(tmp_path, "src/fresh/new.lisp", "(def x\n")
    written(tmp_path, "README.md", "# changed notes\n")
    guard.after_edit(block())
    assert sorted(parser.calls[-1][0]) == ["src/core.lisp", "src/fresh/new.lisp"]
    assert guard.ctx() == {
        "lisp_syntax_errors": [
            "src/core.lisp:3:1: EOF while reading",
            "src/fresh/new.lisp:2:1: EOF while reading",
        ]
    }
    existing.write_text("(ns core)\n", encoding="utf-8")
    created.unlink()
    guard.before_block(block())
    guard.after_edit(block())
    assert guard.ctx() == {}


def test_files_a_block_did_not_change_are_not_parsed(guard, parser, tmp_path):
    written(tmp_path, "src/core.lisp", "(a")
    guard.before_block(block())
    guard.after_edit(block())
    assert parser.calls == []


def test_hidden_and_build_directories_are_not_watched(guard, parser, tmp_path):
    written(tmp_path, "src/core.lisp", "(a)")
    guard.before_block(block())
    written(tmp_path, "node_modules/pkg/x.lisp", "(a")
    written(tmp_path, ".cache/y.lisp", "(a")
    written(tmp_path, "target/classes/z.lisp", "(a")
    guard.after_edit(block())
    assert parser.calls == []
    assert guard.ctx() == {}


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_decides_which_files_are_watched(guard, parser, tmp_path):
    process.run(["git", "init", "-q"], cwd=tmp_path)
    written(tmp_path, ".gitignore", "out/\n")
    ignored = written(tmp_path, "out/generated.lisp", "(a")
    source = written(tmp_path, "src/core.lisp", "(a)")
    guard.before_block(block())
    ignored.write_text("(a (b", encoding="utf-8")
    source.write_text("(a (b", encoding="utf-8")
    guard.after_edit(block())
    assert list(parser.calls[-1][0]) == ["src/core.lisp"]


def test_one_pass_parses_at_most_most_files_and_the_rest_wait(tmp_path, parser):
    guard = SyntaxGuard(
        "lisp",
        (".lisp",),
        parser,
        most_files=2,
        workspace_root=lambda: tmp_path,
        state={},
    )
    guard.before_block(block())
    for name in ("a", "b", "c"):
        written(tmp_path, f"{name}.lisp", "(")
    guard.after_edit(block())
    assert len(guard.ctx()["lisp_syntax_errors"]) == 2
    guard.after_edit(block())
    assert len(guard.ctx()["lisp_syntax_errors"]) == 3


def test_files_the_parser_could_not_read_are_parsed_on_the_next_pass(
    guard, parser, tmp_path
):
    guard.before_block(block())
    written(tmp_path, "a.lisp", "(")
    parser.error = RuntimeError("busy")
    guard.after_edit(block())
    assert guard.ctx() == {}
    parser.error = None
    guard._quiet_until = 0.0
    guard.after_edit(block())
    assert guard.ctx() == {"lisp_syntax_errors": ["a.lisp:1:1: EOF while reading"]}


def test_the_context_names_a_bounded_number_of_files(guard, tmp_path):
    guard.before_block(block())
    for index in range(syntax.MOST_REPORTED + 5):
        written(tmp_path, f"f{index:02}.lisp", "(")
    guard.after_edit(block())
    rows = guard.ctx()["lisp_syntax_errors"]
    assert len(rows) == syntax.MOST_REPORTED + 1
    assert rows[-1] == "... and 5 more files"


def test_each_workspace_keeps_its_own_report(tmp_path, parser):
    state = {}
    first, second = tmp_path / "one", tmp_path / "two"
    written(first, "a.lisp", "(")
    written(second, "a.lisp", "()")
    for root in (first, second):
        guard = SyntaxGuard(
            "lisp",
            (".lisp",),
            parser,
            workspace_root=lambda root=root: root,
            state=state,
        )
        guard.after_edit({"op": "patch", "args": ["a.lisp", []], "result": "patched"})
    one = SyntaxGuard(
        "lisp", (".lisp",), parser, workspace_root=lambda: first, state=state
    )
    two = SyntaxGuard(
        "lisp", (".lisp",), parser, workspace_root=lambda: second, state=state
    )
    assert one.ctx() == {"lisp_syntax_errors": ["a.lisp:1:1: EOF while reading"]}
    assert two.ctx() == {}


def test_a_failing_workspace_lookup_never_breaks_an_operation(parser):
    def missing():
        raise RuntimeError("no session")

    guard = SyntaxGuard("lisp", (".lisp",), parser, workspace_root=missing, state={})
    assert guard.before_patch(patched("(a)", "(a")) is None
    assert guard.before_block(block()) is None
    assert guard.after_edit(block()) is None
    assert guard.ctx() == {}


def test_the_hooks_cover_patch_and_python_execution(guard):
    hooks = [(hook.ops, hook.phase) for hook in guard.op_hooks()]
    assert hooks == [
        (("patch",), "before"),
        (("python_execution",), "before"),
        (("patch", "python_execution"), "after"),
    ]


def test_the_interface_registers_no_syntax_tools(monkeypatch):
    registered = []
    monkeypatch.setattr(vis, "register_extension", registered.append)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "extension.py"))
    assert len(registered) == 1
    assert not registered[0].symbols


def test_hooks_dispatch_only_to_the_parser_for_the_file_suffix(tmp_path):
    calls = []

    def _check_syntax(sources, root):
        calls.append(dict(sources))
        return SyntaxResult.of("example", (), files=len(sources))

    guards = [
        SyntaxGuard(
            language, suffixes, _check_syntax, workspace_root=lambda: tmp_path, state={}
        )
        for language, suffixes in (("lisp", (".lisp",)), ("python", (".py", ".pyi")))
    ]
    for guard in guards:
        guard.op_hooks()[0].fn(patched("before", "after", path="src/example.py"))
    assert calls == [{"src/example.py": "after"}]


def test_a_guard_needs_a_suffix(parser):
    with pytest.raises(ValueError, match="suffix"):
        SyntaxGuard("lisp", (), parser)


def test_a_new_file_in_an_unwatched_directory_is_found_on_the_next_listing(
    guard, parser, tmp_path, monkeypatch
):
    empty = tmp_path / "empty"
    empty.mkdir()
    guard.before_block(block())
    written(tmp_path, "empty/late.lisp", "(")
    monkeypatch.setattr(syntax, "REFRESH_S", -1.0)
    guard.before_block(block())
    guard.after_edit(block())
    assert guard.ctx() == {
        "lisp_syntax_errors": ["empty/late.lisp:1:1: EOF while reading"]
    }
    assert os.path.isdir(empty)
