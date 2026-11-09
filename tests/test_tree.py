"""A tree reports changed files from stat calls and forgets files that are gone."""

import os
import subprocess

from vis_lang_interface.tree import Tree, listing


def _write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


def _everything(_path):
    return True


def test_changes_report_edits_new_and_gone_files_and_settle_takes_them(tmp_path):
    kept = _write(tmp_path, "src/kept.txt", "a")
    edited = _write(tmp_path, "src/edited.txt", "a")
    gone = _write(tmp_path, "gone.txt", "a")
    tree = Tree(tmp_path, [kept, edited, gone], _everything)
    assert tree.changes(_everything) == {}

    _write(tmp_path, "src/edited.txt", "longer")
    added = _write(tmp_path, "src/added.txt", "new")
    os.remove(gone)
    changed = tree.changes(_everything)
    assert set(changed) == {edited, added, gone}
    assert changed[gone] is None

    tree.settle(changed)
    assert gone not in tree.seen
    assert tree.changes(_everything) == {}


def test_changes_keep_out_what_git_ignores(tmp_path):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)
    _write(tmp_path, ".gitignore", "*.log\nmade/\n")
    _write(tmp_path, "a.txt", "a")
    _write(tmp_path, "out/.gitignore", "*\n")
    _write(tmp_path, "out/data.json", "{}")
    _write(tmp_path, "old.log", "crash")
    tree = Tree(tmp_path, listing(tmp_path), _everything)

    # New root entries move the root mtime, so the next check reads the root again.
    _write(tmp_path, "made/x.js", "x")
    added = _write(tmp_path, "b.txt", "b")
    nested = _write(tmp_path, "new/c.txt", "c")
    assert set(tree.changes(_everything)) == {added, nested}
