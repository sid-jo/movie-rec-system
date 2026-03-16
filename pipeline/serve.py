"""
Serve recommendations - wraps src.recommender.get_recommendations.
"""
import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.recommender import get_recommendations

__all__ = ["get_recommendations"]
