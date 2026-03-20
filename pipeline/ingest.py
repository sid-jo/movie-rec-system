from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Optional

from pipeline.paths import default_paths


@dataclass(frozen=True)
class IngestResult:
    downloaded: int
    skipped_existing: int
    output_dir: str


def run(
    bucket_name: str,
    prefix: str,
    output_dir: str,
    project_id: str | None = None,
    max_results: int | None = None,
    gcs_client=None,
) -> IngestResult:
    """
    Download raw Kafka log jsonl blobs from GCS to a local directory.

    This is intentionally thin; `gcs_client` is injectable for tests.
    """
    os.makedirs(output_dir, exist_ok=True)

    if gcs_client is None:
        from google.cloud import storage

        gcs_client = storage.Client(project=project_id) if project_id else storage.Client()

    bucket = gcs_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix, max_results=max_results))

    downloaded = 0
    skipped = 0
    for blob in blobs:
        filename = blob.name.split("/")[-1]
        if not filename:
            continue
        local_path = os.path.join(output_dir, filename)
        if os.path.exists(local_path):
            skipped += 1
            continue
        blob.download_to_filename(local_path)
        downloaded += 1

    return IngestResult(downloaded=downloaded, skipped_existing=skipped, output_dir=output_dir)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Ingest raw logs from GCS → local data/raw_logs")
    p.add_argument("--bucket", required=True, help="GCS bucket name (e.g., mlip-team2-movielog)")
    p.add_argument("--prefix", default="raw_logs/", help="GCS prefix for raw logs")
    p.add_argument("--project-id", default=None, help="GCP project id (optional)")
    p.add_argument("--max-results", type=int, default=None, help="Limit number of blobs downloaded")
    p.add_argument("--output-dir", default=None, help="Local output dir for jsonl files")
    args = p.parse_args(argv)

    paths = default_paths()
    out_dir = args.output_dir or paths.data_raw_logs

    print(
        f"[ingest] starting: bucket=gs://{args.bucket}/{args.prefix} "
        f"→ output_dir={out_dir}"
    )

    res = run(
        bucket_name=args.bucket,
        prefix=args.prefix,
        output_dir=out_dir,
        project_id=args.project_id,
        max_results=args.max_results,
    )
    print(
        f"[ingest] completed: downloaded={res.downloaded} "
        f"skipped_existing={res.skipped_existing} → {res.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

