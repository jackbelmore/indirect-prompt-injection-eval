"""
One place that knows where the pipeline's files live.

Every default path in the harness is resolved from this file rather than from the working
directory, so `python3 src/runner.py` does the same thing whether it is run from the pipeline
root, from inside `src/`, or from anywhere else on the machine. Passing an explicit path on the
command line still overrides the default, and a relative path passed that way is still read
relative to wherever you are standing.

Anything the harness writes goes under ROOT, never into the caller's working directory.
"""

from pathlib import Path

# src/paths.py -> src/ -> the pipeline root.
ROOT = Path(__file__).resolve().parents[1]

PAYLOAD_LIBRARY = ROOT / "payloads" / "library.json"
DOCUMENTS_DIR = ROOT / "documents"
RESULTS_DIR = ROOT / "results"

DEFAULT_RESULTS_FILE = RESULTS_DIR / "audit_results.jsonl"
PIPELINE_LOG = RESULTS_DIR / "evaluation_pipeline.log"
SUMMARY_CSV = RESULTS_DIR / "summary_table.csv"
