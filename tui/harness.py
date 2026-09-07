"""
Lifecycle check for the dashboard: start it on a pseudo-terminal and confirm it is still
running two seconds later, rather than having exited on a missing dependency or a panic.

Run by run_tests.sh. Needs Go, but no model and no Ollama.
"""

import pty
import os
import subprocess
import time
import sys
from pathlib import Path

# The directory this file sits in, so the check runs from any checkout on any machine.
TUI_DIR = Path(__file__).resolve().parent

def test_tui():
    master, slave = pty.openpty()
    
    process = subprocess.Popen(
        ["go", "run", "."],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=TUI_DIR,
        close_fds=True
    )
    
    os.close(slave)
    
    # Wait up to 2 seconds to see if it exits
    start_time = time.time()
    while time.time() - start_time < 2:
        if process.poll() is not None:
            break
        time.sleep(0.1)
        
    exit_code = process.poll()
    
    # Read output
    output = b""
    try:
        os.set_blocking(master, False)
        while True:
            data = os.read(master, 1024)
            if not data:
                break
            output += data
    except BlockingIOError:
        pass
    except OSError:
        pass
        
    if exit_code is not None:
        print(f"Process exited prematurely with code {exit_code}")
        print("Output:")
        print(output.decode('utf-8', errors='replace'))
        sys.exit(1)
    else:
        print("Process is running successfully.")
        process.terminate()
        sys.exit(0)

if __name__ == "__main__":
    test_tui()
