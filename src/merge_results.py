"""Merge multiple .jsonl result files into audit_results.jsonl for analysis."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description="Merge JSONL files")
parser.add_argument("input_files", nargs='+', help="Files to merge")
parser.add_argument("--output", "-o", required=True, help="Output file")
args = parser.parse_args()

output = Path(args.output)
with open(output, 'w') as out:
    for path in args.input_files:
        with open(path) as f:
            out.write(f.read())
print(f"Merged {len(args.input_files)} files → {output}")
