# Extra edge-case checks for duration parsing.
import pytest

from loglib.parser import parse_duration


def test_duration_minutes_only():
    assert parse_duration("45m") == 2700


def test_duration_combined():
    assert parse_duration("1h30m") == 5400


def test_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("soon")
