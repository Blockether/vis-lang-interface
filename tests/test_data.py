"""JSON and TOML verdicts come from the standard library's own parsers."""

import pytest

from vis_lang_interface import data


def test_valid_json_has_no_findings():
    assert data.check_source('{"a": 1}', "json") == ()


def test_invalid_json_is_located():
    findings = data.check_source('{"a": }', "json", "a.json")
    assert len(findings) == 1
    assert findings[0].path == "a.json"
    assert findings[0].line == 1
    assert findings[0].level == "error"


def test_invalid_toml_is_located():
    findings = data.check_source("a = [1,\n", "toml", "a.toml")
    assert len(findings) == 1
    assert findings[0].line >= 1


def test_unknown_language_is_refused():
    with pytest.raises(ValueError, match="unsupported"):
        data.check_source("x", "yaml")


def test_format_json_indents_and_ends_with_a_newline():
    assert data.format_json('{"a":[1,2]}') == '{\n  "a": [\n    1,\n    2\n  ]\n}\n'


def test_format_files_reports_and_writes(tmp_path):
    file = tmp_path / "a.json"
    file.write_text('{"a":1}', encoding="utf-8")
    preview = data.format_files([file])
    assert preview.changed == (str(file),)
    assert file.read_text(encoding="utf-8") == '{"a":1}'
    written = data.format_files([file], is_written=True)
    assert written.is_written is True
    assert file.read_text(encoding="utf-8") == '{\n  "a": 1\n}\n'
    assert data.format_files([file]).unchanged == (str(file),)


def test_check_files_counts_every_file(tmp_path):
    good = tmp_path / "good.json"
    good.write_text("[]", encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text("a = [1,", encoding="utf-8")
    result = data.check_files([good, bad])
    assert result.files == 2
    assert result.errors == 1
