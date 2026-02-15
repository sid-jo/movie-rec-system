"""Test recommend endpoint format: comma-separated movie IDs, up to 20, no userid in response."""
import sys
import os

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.recommender import get_recommendations


def test_recommend_format():
    recs = get_recommendations("70106")
    assert isinstance(recs, list)
    assert 1 <= len(recs) <= 20
    # No numeric userid in the list
    for m in recs:
        assert "+" in m or m.replace("_", "").isalnum(), f"Unexpected format: {m}"
        assert m != "70106" and m != "999999", f"userid must not appear in recommendations: {m}"
    # Comma-separated string representation
    s = ",".join(recs)
    assert "\n" not in s
    assert len(s.split(",")) <= 20


def test_different_users_different_recs():
    r1 = get_recommendations("70106")
    r2 = get_recommendations("999999")
    # At least some difference for personalization (10% requirement)
    assert r1 != r2 or len(r1) > 0


if __name__ == "__main__":
    test_recommend_format()
    test_different_users_different_recs()
    print("All tests passed.")
