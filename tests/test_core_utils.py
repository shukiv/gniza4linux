"""Tests for lib.core.utils — pure utility functions."""
import re
from lib.core.utils import (
    make_timestamp,
    human_size,
    human_duration,
    validate_timestamp,
    get_hostname,
    shquote,
)


class TestMakeTimestamp:
    def test_format(self):
        ts = make_timestamp()
        assert re.match(r'^\d{4}-\d{2}-\d{2}T\d{6}$', ts)

    def test_length(self):
        ts = make_timestamp()
        assert len(ts) == 17


class TestHumanSize:
    def test_bytes(self):
        assert human_size(0) == "0 B"
        assert human_size(512) == "512 B"
        assert human_size(1023) == "1023 B"

    def test_kilobytes(self):
        assert human_size(1024) == "1.0 KB"
        assert human_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert human_size(1048576) == "1.0 MB"
        assert human_size(1572864) == "1.5 MB"

    def test_gigabytes(self):
        assert human_size(1073741824) == "1.0 GB"

    def test_terabytes(self):
        assert human_size(1099511627776) == "1.0 TB"

    def test_petabytes(self):
        assert human_size(1125899906842624) == "1.0 PB"

    def test_negative(self):
        assert human_size(-100) == "0 B"


class TestHumanDuration:
    def test_seconds_only(self):
        assert human_duration(0) == "0s"
        assert human_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert human_duration(90) == "1m 30s"
        assert human_duration(60) == "1m 0s"

    def test_hours_minutes_seconds(self):
        assert human_duration(3661) == "1h 1m 1s"
        assert human_duration(3600) == "1h 0m 0s"

    def test_negative(self):
        assert human_duration(-5) == "0s"


class TestValidateTimestamp:
    def test_valid(self):
        assert validate_timestamp("2026-03-24T120000") is True

    def test_invalid_format(self):
        assert validate_timestamp("2026-03-24 12:00:00") is False

    def test_empty(self):
        assert validate_timestamp("") is False

    def test_wrong_separators(self):
        assert validate_timestamp("20260324T120000") is False

    def test_too_short(self):
        assert validate_timestamp("2026-03-24T1200") is False

    def test_letters(self):
        assert validate_timestamp("abcd-ef-ghTijklmn") is False


class TestGetHostname:
    def test_returns_string(self):
        hn = get_hostname()
        assert isinstance(hn, str)
        assert len(hn) > 0


class TestShquote:
    def test_simple(self):
        assert shquote("hello") == "hello"

    def test_spaces(self):
        result = shquote("hello world")
        assert "hello world" in result

    def test_single_quotes(self):
        result = shquote("it's")
        # Must be safely quoted
        assert "'" in result or "\\'" in result

    def test_special_chars(self):
        result = shquote("foo;bar&&baz")
        # Verify the dangerous chars are contained/escaped
        assert result != "foo;bar&&baz"

    def test_empty(self):
        result = shquote("")
        assert result == "''"
