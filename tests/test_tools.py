"""The extension's own tools walk directories and refuse empty selections."""

import pytest

from vis_lang_interface.tools import DataTools


def test_check_walks_a_directory(tmp_path):
    (tmp_path / "a.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "b.toml").write_text("a = 1", encoding="utf-8")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "ignored.json").write_text("{", encoding="utf-8")
    result = DataTools().check([str(tmp_path)])
    assert result.files == 2
    assert result.is_clean is True


def test_check_refuses_paths_without_data_files(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="no JSON or TOML file"):
        DataTools().check([str(tmp_path)])


def test_format_refuses_paths_without_json(tmp_path):
    (tmp_path / "a.toml").write_text("a = 1", encoding="utf-8")
    with pytest.raises(ValueError, match="no JSON file"):
        DataTools().format([str(tmp_path)])


def test_format_rewrites_only_when_asked(tmp_path):
    file = tmp_path / "a.json"
    file.write_text('{"a":1}', encoding="utf-8")
    assert DataTools().format([str(file)]).is_written is False
    assert file.read_text(encoding="utf-8") == '{"a":1}'
    assert DataTools().format([str(file)], is_written=True).changed == (str(file),)
