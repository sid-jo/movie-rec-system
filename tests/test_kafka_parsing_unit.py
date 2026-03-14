from src.kafka_parsing import parse_log_entry


def test_parse_rating():
    line = "2026-03-01T00:00:00Z,1,/rate/toy+story+1995=5"
    obj = parse_log_entry(line)
    assert obj is not None
    assert obj["type"] == "rating"
    assert obj["userid"] == "1"
    assert obj["movieid"] == "toy+story+1995"
    assert obj["rating"] == 5


def test_parse_watch():
    line = "2026-03-01T00:01:00Z,1,/data/m/toy+story+1995/10.mpg"
    obj = parse_log_entry(line)
    assert obj is not None
    assert obj["type"] == "watch"
    assert obj["movieid"] == "toy+story+1995"
    assert obj["minute"] == 10


def test_parse_recommendation():
    line = "2026-03-01T00:02:00Z,1,recommendation request srv, status 200, result: [a,b], 12ms"
    obj = parse_log_entry(line)
    assert obj is not None
    assert obj["type"] == "recommendation"
    assert obj["status"] == 200
    assert obj["recommendations"] == "a,b"


def test_parse_signup():
    line = "2026-03-01T00:03:00Z,2,create_account"
    obj = parse_log_entry(line)
    assert obj is not None
    assert obj["type"] == "signup"


def test_parse_bad_line_returns_none():
    assert parse_log_entry("nope") is None

