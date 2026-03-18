"""Tests for lib.config — Python config parser."""
from pathlib import Path
from lib.config import parse_conf, write_conf


def test_parse_basic(tmp_path):
    conf = tmp_path / "test.conf"
    conf.write_text('KEY1="value1"\nKEY2="value2"\n')
    data = parse_conf(conf)
    assert data["KEY1"] == "value1"
    assert data["KEY2"] == "value2"


def test_parse_single_quotes(tmp_path):
    conf = tmp_path / "test.conf"
    conf.write_text("KEY1='value1'\n")
    data = parse_conf(conf)
    assert data["KEY1"] == "value1"


def test_parse_no_quotes(tmp_path):
    conf = tmp_path / "test.conf"
    conf.write_text("KEY1=noquotes\n")
    data = parse_conf(conf)
    assert data["KEY1"] == "noquotes"


def test_parse_skips_comments(tmp_path):
    conf = tmp_path / "test.conf"
    conf.write_text('# comment\nKEY="val"\n  # indented\n')
    data = parse_conf(conf)
    assert data == {"KEY": "val"}


def test_parse_skips_shell_injection(tmp_path):
    conf = tmp_path / "test.conf"
    conf.write_text('SAFE="ok"\n$(touch /tmp/pwned)\neval bad\n')
    data = parse_conf(conf)
    assert data == {"SAFE": "ok"}


def test_parse_empty_value(tmp_path):
    conf = tmp_path / "test.conf"
    conf.write_text('KEY=""\n')
    data = parse_conf(conf)
    assert data["KEY"] == ""


def test_parse_nonexistent_file(tmp_path):
    conf = tmp_path / "nonexistent.conf"
    data = parse_conf(conf)
    assert data == {}


def test_write_roundtrip(tmp_path):
    conf = tmp_path / "test.conf"
    original = {"KEY1": "hello", "KEY2": "world"}
    write_conf(conf, original)
    data = parse_conf(conf)
    assert data["KEY1"] == "hello"
    assert data["KEY2"] == "world"


def test_write_escapes_quotes(tmp_path):
    conf = tmp_path / "test.conf"
    write_conf(conf, {"KEY": 'has "quotes"'})
    content = conf.read_text()
    assert '\\"' in content  # quotes escaped
    data = parse_conf(conf)
    assert "quotes" in data["KEY"]


def test_write_sets_permissions(tmp_path):
    conf = tmp_path / "test.conf"
    write_conf(conf, {"KEY": "val"})
    assert oct(conf.stat().st_mode & 0o777) == oct(0o600)
