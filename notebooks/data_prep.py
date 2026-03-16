#!/usr/bin/env python3
"""
Data preparation script - works entirely with local files
Processes Kafka logs into clean training data.
Run from project root: python notebooks/data_prep.py
"""
import os
import sys

# Ensure we run from project root (parent of notebooks/)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
os.chdir(_project_root)

from pipeline.data_prep import run as data_prep_run

if __name__ == "__main__":
    print("=" * 60)
    print("DATA PREPARATION - WORKING LOCALLY")
    print("=" * 60)

    print("\n1. Loading metadata and processing logs...")
    summary = data_prep_run(
        raw_logs_dir="data/raw_logs",
        metadata_dir="metadata",
        output_dir="data/processed",
    )

    print(f"\n   Ratings: {summary['ratings']:,}")
    print(f"   Watches: {summary['watches']:,}")
    print(f"   Unique users: {summary['users']:,}")
    print(f"   Unique movies: {summary['movies']:,}")

    print("\n✓ Saved to data/processed/")
    print("   - ratings.csv")
    print("   - watches.csv")
    print("   - recommendations.csv")
    print("   - signups.csv")

    print("\n" + "=" * 60)
    print("Data preparation complete!")
    print("   You can now train models using data/processed/*.csv")
    print("=" * 60)
