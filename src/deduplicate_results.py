import json
import sys
from typing import Dict, Any

from paths import DEFAULT_RESULTS_FILE

def deduplicate(input_file: str, output_file: str):
    records = []
    with open(input_file, 'r') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    
    unique_records: Dict[str, Any] = {}
    for r in records:
        # CRITICAL: Include condition in uniqueness key to avoid squashing different conditions
        key = f"{r.get('model')}_{r.get('condition')}_{r.get('document_name')}_{r.get('trial_index')}"
        unique_records[key] = r  # Keeps the latest occurrence

    with open(output_file, 'w') as f:
        for r in unique_records.values():
            f.write(json.dumps(r) + '\n')

if __name__ == "__main__":
    in_file = DEFAULT_RESULTS_FILE
    if len(sys.argv) > 1:
        in_file = sys.argv[1]
    
    # Just in case the file doesn't exist yet or is empty
    try:
        deduplicate(in_file, in_file)
        print(f"Successfully deduplicated records in {in_file}")
    except FileNotFoundError:
        print(f"Error: Could not find {in_file}")
