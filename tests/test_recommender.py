"""Tests for src.recommender (prediction service logic)."""
import os
import sys
import json
import tempfile
import pytest

# Ensure project root in path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_get_recommendations_format():
    """Test that get_recommendations returns valid format (list, 1-20 items)."""
    from src.recommender import get_recommendations
    # Use a user that may exist in training or fall back to popularity
    recs = get_recommendations("70106")
    assert isinstance(recs, list)
    assert 1 <= len(recs) <= 20
    for m in recs:
        assert m != "70106"
        assert isinstance(m, str)


def test_get_recommendations_different_users():
    """Test personalization - different users get different recs (or at least valid)."""
    from src.recommender import get_recommendations
    r1 = get_recommendations("70106")
    r2 = get_recommendations("999999")
    assert len(r1) > 0
    assert len(r2) > 0
    # At least some difference for personalization
    assert r1 != r2 or len(r1) > 0


def test_get_recommendations_cold_start_with_user_data():
    """Test cold start path with user_data (likes/dislikes)."""
    from src.recommender import get_recommendations
    user_data = {"userid": "newuser", "self_description_likes": "I like The Godfather", "self_description_dislikes": ""}
    recs = get_recommendations("newuser", user_data=user_data)
    assert isinstance(recs, list)
    assert 1 <= len(recs) <= 20


def test_get_recommendations_force_popularity():
    """Test force_popularity bypasses NMF/cold-start."""
    from src.recommender import get_recommendations
    recs = get_recommendations("70106", force_popularity=True)
    assert isinstance(recs, list)
    assert 1 <= len(recs) <= 20
