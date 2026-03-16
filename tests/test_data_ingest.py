"""Tests for pipeline.data_ingest."""
import pytest
from pipeline.data_ingest import parse_log_line, parse_json_event


def test_parse_log_line_watch():
    line = "2025-12-25T03:20:08,50451,GET /data/m/superman+1978/0.mpg"
    result = parse_log_line(line)
    assert result is not None
    assert result["type"] == "watch"
    assert result["userid"] == "50451"
    assert result["movieid"] == "superman+1978"
    assert result["minute"] == 0


def test_parse_log_line_rating():
    line = "2025-12-25T03:22:05,50451,GET /rate/superman+1978=8"
    result = parse_log_line(line)
    assert result is not None
    assert result["type"] == "rating"
    assert result["userid"] == "50451"
    assert result["movieid"] == "superman+1978"
    assert result["rating"] == 8


def test_parse_log_line_recommendation():
    line = "2025-12-25T03:24:10,50451,recommendation request status 200 result: [m1,m2]"
    result = parse_log_line(line)
    assert result is not None
    assert result["type"] == "recommendation"
    assert result["status"] == 200


def test_parse_log_line_signup():
    line = "2025-12-25T03:25:00,50451,create_account"
    result = parse_log_line(line)
    assert result is not None
    assert result["type"] == "signup"


def test_parse_log_line_malformed():
    assert parse_log_line("") is None
    assert parse_log_line("only,two") is None
    assert parse_log_line("a,b,c") is None  # unknown action
    assert parse_log_line("  ,  ,  ") is None


def test_parse_json_event_valid():
    line = '{"type": "watch", "userid": "u1", "movieid": "m1"}'
    result = parse_json_event(line)
    assert result == {"type": "watch", "userid": "u1", "movieid": "m1"}


def test_parse_json_event_invalid():
    assert parse_json_event("") is None
    assert parse_json_event("not json") is None
    assert parse_json_event("{invalid") is None
