import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

def test_pipeline_end_to_end_schema():
    """
    Runs the Python pipeline in a minimal configuration against the test payload.
    Validates that the output JSONL structurally conforms to the TrialResult schema.
    """
    # Define paths
    project_root = Path(__file__).parent.parent
    test_docs = project_root / "test_documents"
    output_file = project_root / "results" / "pytest_audit.jsonl"
    
    # Ensure test doc exists
    test_docs.mkdir(parents=True, exist_ok=True)
    test_doc_path = test_docs / "P000_smoke_test.txt"
    test_doc_path.write_text("This is a tiny payload designed purely for testing pipeline execution.")
    
    # Clean up previous run if exists
    if output_file.exists():
        output_file.unlink()

    # Run the pipeline for exactly 1 trial on the fastest local model
    runner_script = project_root / "src" / "runner.py"
    
    # Check if ollama has dolphin-phi, otherwise test might fail gracefully
    # For now we assume dolphin-phi:latest exists based on prior inspection
    cmd = [
        "python3", str(runner_script),
        "--models", "dolphin-phi:latest",
        "--docs-dir", str(test_docs),
        "--trials", "1",
        "--output-file", str(output_file),
        "--force"
    ]
    
    print(f"\nRunning command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root))
    
    assert result.returncode == 0, f"Pipeline execution failed!\nStdout: {result.stdout}\nStderr: {result.stderr}"
    assert output_file.exists(), "Results file was not created by the pipeline."
    
    lines = output_file.read_text().strip().split("\n")
    assert len(lines) > 0, "Results file is empty!"
    
    # Validate each line adheres to TrialResult dataclass structure
    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue # Might be progress bar log, though Python backend strictly outputs json lines now
            
        # Ignore progress updates, look only at actual results
        if data.get("type") == "progress":
            continue
            
        assert "timestamp" in data, "Missing timestamp in TrialResult"
        assert "model" in data, "Missing model in TrialResult"
        assert "condition" in data, "Missing condition in TrialResult"
        assert "document_name" in data, "Missing document_name in TrialResult"
        assert "trial_index" in data, "Missing trial_index in TrialResult"
        assert "status" in data, "Missing status in TrialResult"
        
        # If the trial was successful, assert response exists
        if data["status"] == "success":
            assert "llm_response" in data, "Missing llm_response for successful trial"
            assert "reasoning" in data, "Missing reasoning for successful trial"
            assert isinstance(data["called_tools"], list), "called_tools should be a list"
            
        # Verify timestamp format (ISO 8601)
        try:
            datetime.fromisoformat(data["timestamp"])
        except ValueError:
            assert False, f"Invalid timestamp format: {data['timestamp']}"
