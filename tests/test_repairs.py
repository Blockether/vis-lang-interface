"""Repair decisions preserve validation, changed spans and concurrent writes."""

from types import SimpleNamespace

import pytest

from vis_lang_interface import Diagnostic, SyntaxResult
from vis_lang_interface.syntax import SyntaxGuard


def parser(sources, root):
    return SyntaxResult.of(
        "lisp",
        [
            Diagnostic(p, 1, 1, "error", "Unbalanced")
            for p, s in sources.items()
            if s.count("(") != s.count(")")
        ],
        len(sources),
    )


def make_guard(root, repair, check=parser):
    return SyntaxGuard(
        "lisp", (".lisp",), check, repair=repair, workspace_root=lambda: root, state={}
    )


def call(before, after):
    return {
        "op": "patch",
        "args": ["a.lisp", []],
        "preview": {
            "path": "a.lisp",
            "before": before,
            "after": after,
            "spans": [[1, 1]],
        },
    }


def fixed(source, **kwargs):
    return SimpleNamespace(
        source=source.replace("(b", "(b)"), notes=("Closed the form.",)
    )


def test_patch_returns_a_repair_without_writing(tmp_path):
    path = tmp_path / "a.lisp"
    path.write_text("(a)\n")
    seen = []

    def repair(source, **kwargs):
        seen.append((source, kwargs))
        return fixed(source)

    guard = make_guard(tmp_path, repair)
    result = guard.before_patch(call("(a)\n", "(b\n"))
    assert result == {
        "marker": "repair",
        "source": "(b)\n",
        "notes": ["Closed the form."],
    }
    assert path.read_text() == "(a)\n"
    assert seen[0][1]["original"] == "(a)\n"
    assert seen[0][1]["spans"] == [[1, 1]]
    assert seen[0][1]["parses_clean"]("(b)")


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        SimpleNamespace(source="(b", notes=("Failed.",)),
        SimpleNamespace(source="(b)", notes=()),
        SimpleNamespace(source="(b)", notes="Invalid"),
    ],
)
def test_invalid_candidates_still_refuse_the_patch(tmp_path, candidate):
    guard = make_guard(tmp_path, lambda *a, **kw: candidate)
    verdict = guard.before_patch(call("(a)", "(b"))
    assert verdict is not None
    assert verdict["marker"] == "block"


def test_valid_edits_never_run_repair(tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("Repair must not change valid source")

    assert make_guard(tmp_path, unexpected).before_patch(call("(a)", "(b)")) is None


def test_unavailable_parser_never_authorizes_repair(tmp_path):
    def unavailable(*args):
        raise RuntimeError("Reader is unavailable")

    guard = make_guard(tmp_path, fixed, check=unavailable)
    assert guard.before_patch(call("(a)", "(b")) is None


def test_after_block_repairs_changed_files_and_reports_the_diff(tmp_path):
    path = tmp_path / "a.lisp"
    path.write_bytes(b"(a)\r\n")
    path.chmod(0o640)
    guard = make_guard(tmp_path, fixed)
    block = {"op": "python_execution", "args": [{"code": "..."}], "result": {}}
    guard.before_block(block)
    path.write_bytes(b"(b\r\n")
    guard.after_edit(block)
    assert path.read_bytes() == b"(b)\r\n"
    assert path.stat().st_mode & 0o777 == 0o640
    context = guard.ctx()
    assert "lisp_syntax_errors" not in context
    assert "Closed the form." in str(context["lisp_syntax_repairs"])
    assert "+(b)" in str(context["lisp_syntax_repairs"])
    assert not list(tmp_path.glob("*.tmp"))


def test_after_block_does_not_overwrite_a_concurrent_write(tmp_path):
    path = tmp_path / "a.lisp"
    path.write_text("(a)\n")

    def competing(source, **kwargs):
        path.write_text("(concurrent)\n")
        return fixed(source)

    guard = make_guard(tmp_path, competing)
    block = {"op": "python_execution", "args": [{"code": "..."}], "result": {}}
    guard.before_block(block)
    path.write_text("(b\n")
    guard.after_edit(block)
    assert path.read_text() == "(concurrent)\n"
    assert "lisp_syntax_repairs" not in guard.ctx()
    assert not list(tmp_path.glob("*.tmp"))


def test_after_block_does_not_replace_a_symbolic_link(tmp_path):
    target = tmp_path / "target.lisp"
    target.write_text("(b\n")
    link = tmp_path / "link.lisp"
    link.symlink_to(target)
    guard = make_guard(tmp_path, fixed)
    assert not guard._write_repair(link, "(b\n", "(b)\n")
    assert target.read_text() == "(b\n"
    assert link.is_symlink()


def test_failed_atomic_replace_keeps_original_and_removes_temporary_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "a.lisp"
    path.write_text("(b\n")
    guard = make_guard(tmp_path, fixed)

    def failed_replace(*args):
        raise OSError("Cannot replace this file")

    monkeypatch.setattr("vis_lang_interface.syntax.os.replace", failed_replace)
    assert not guard._write_repair(path, "(b\n", "(b)\n")
    assert path.read_text() == "(b\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.lisp"]
