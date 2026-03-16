#!/usr/bin/env python3
"""Offline evaluation - runs compare_models and saves evaluation_results.json."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.compare_models import run_offline_eval_and_save, main

if __name__ == "__main__":
    main()
    path = run_offline_eval_and_save()
    print("Results saved to", path)
