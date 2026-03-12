from __future__ import annotations

import argparse
import json
import os
from typing import Any

from pipeline.data_quality import summarize_issues, validate_course_movie, validate_course_user, validate_recommend_response_text
from pipeline.paths import default_paths


def run(metadata_dir: str, output_path: str) -> dict[str, Any]:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    issues = []

    users_path = os.path.join(metadata_dir, "users.json")
    movies_path = os.path.join(metadata_dir, "movies.json")
    if os.path.exists(users_path):
        with open(users_path) as f:
            users = json.load(f)
        if isinstance(users, dict):
            for u in list(users.values())[:500]:
                if isinstance(u, dict):
                    issues.extend(validate_course_user(u))
        else:
            issues.append(
                {"source": "course_api.user", "severity": "error", "message": "users.json is not a dict keyed by user_id"}
            )
    else:
        issues.append({"source": "course_api.user", "severity": "warning", "message": "users.json missing"})

    if os.path.exists(movies_path):
        with open(movies_path) as f:
            movies = json.load(f)
        if isinstance(movies, dict):
            for m in list(movies.values())[:500]:
                if isinstance(m, dict):
                    issues.extend(validate_course_movie(m))
        else:
            issues.append(
                {"source": "course_api.movie", "severity": "error", "message": "movies.json is not a dict keyed by movie_id"}
            )
    else:
        issues.append({"source": "course_api.movie", "severity": "warning", "message": "movies.json missing"})

    # Recommend API schema check (local function contract)
    try:
        from src.recommender import get_recommendations

        recs = get_recommendations("1")
        text = ",".join(recs) if isinstance(recs, list) else str(recs)
        issues.extend(validate_recommend_response_text(text))
    except Exception as e:
        issues.append({"source": "recommend_api", "severity": "warning", "message": f"could not generate sample recs: {e}"})

    report = {"report_type": "schema_check", **summarize_issues(issues)}
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Schema checks for metadata + recommend API contract")
    p.add_argument("--metadata-dir", default=None)
    p.add_argument("--output", default=None, help="Path to write schema_report.json")
    args = p.parse_args(argv)

    paths = default_paths()
    md_dir = args.metadata_dir or paths.metadata_dir
    out = args.output or os.path.join(paths.reports_dir, "schema_report.json")
    rep = run(metadata_dir=md_dir, output_path=out)
    print(f"wrote {out} (errors={rep['error_count']} warnings={rep['warning_count']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

