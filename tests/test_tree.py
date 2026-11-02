"""A tree reports changed files from stat calls and forgets files that are gone."""

import os

from vis_lang_interface.tree import Tree


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
