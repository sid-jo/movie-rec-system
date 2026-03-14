import pytest

from src.recommender import _extract_movies_from_description, get_recommendations


def test_extract_movies_from_description_handles_empty():
    assert _extract_movies_from_description("", {"toy story": "toy+story+1995"}) == []
    assert _extract_movies_from_description(None, {"toy story": "toy+story+1995"}) == []


def test_extract_movies_from_description_matches_simple_title():
    title_to_id = {"toy story": "toy+story+1995", "the godfather": "the+godfather+1972"}
    found = _extract_movies_from_description("I like Toy Story and The Godfather", title_to_id)
    assert "toy+story+1995" in found
    assert "the+godfather+1972" in found


def test_get_recommendations_never_crashes_on_weird_user_data():
    # Even if artifacts/metadata are missing, recommender should fall back.
    recs = get_recommendations("123", user_data={"self_description_likes": 123, "self_description_dislikes": []})
    assert isinstance(recs, list)
    assert 0 <= len(recs) <= 20

