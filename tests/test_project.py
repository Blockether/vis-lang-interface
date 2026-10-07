"""Finding the project directory, its source files and list arguments."""

from pathlib import Path

import pytest

from vis_lang_interface import source_files, string_list


def test_one_bare_string_is_one_entry():
    # Regression for Blockether/vis#324: `tuple("/src/app.py")` gave one path
    # for each character, and `/` made a lint walk the whole filesystem.
    assert string_list("/src/app.py") == ("/src/app.py",)
    assert string_list(Path("src") / "app.py") == (str(Path("src") / "app.py"),)


def test_a_list_keeps_its_entries_and_none_is_empty():
    assert string_list(["a.py", Path("b.py")]) == ("a.py", "b.py")
    assert string_list(("my.ns-test",)) == ("my.ns-test",)
    assert string_list(None) == ()
    assert string_list(()) == ()


@pytest.mark.parametrize("value", [b"a.py", 7, ["a.py", 7], [None]])
def test_other_values_are_refused(value):
    with pytest.raises(TypeError, match="expected a string"):
        string_list(value)


def test_source_files_reads_a_bare_string_as_one_path(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    assert source_files(str(tmp_path), (".py",)) == (tmp_path.resolve() / "app.py",)


def test_source_files_skips_ignored_directories_and_other_suffixes(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("")
    (tmp_path / "pkg" / "notes.txt").write_text("")
    for ignored in ("node_modules", ".venv", "__pycache__"):
        (tmp_path / ignored).mkdir()
        (tmp_path / ignored / "b.py").write_text("")
    found = source_files([str(tmp_path)], (".py",))
    assert found == (tmp_path.resolve() / "pkg" / "a.py",)


def test_source_files_stops_at_the_limit(tmp_path):
    for index in range(10):
        (tmp_path / f"m{index}.py").write_text("")
    found = source_files([str(tmp_path)], (".py",), limit=3)
    assert [path.name for path in found] == ["m0.py", "m1.py", "m2.py"]


def test_source_files_refuses_the_filesystem_root():
    root = Path(Path.cwd().anchor)
    with pytest.raises(ValueError, match="filesystem root"):
        source_files(str(root), (".py",))


def test_source_files_reads_one_file_and_refuses_a_missing_one(tmp_path):
    one = tmp_path / "one.py"
    one.write_text("")
    assert source_files([one], (".py",)) == (one.resolve(),)
    with pytest.raises(FileNotFoundError):
        source_files([tmp_path / "missing.py"], (".py",))
