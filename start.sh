#!/usr/bin/env bash
#
# Single entry point. Checks what is installed, sets up a Python environment,
# generates the test documents if they are missing, and launches the dashboard.
#
#   ./start.sh
#
# Nothing in this project ever executes a command or reads a real file on your
# machine. The MCP server it talks to is a mock that only logs what the model
# tried to do.

set -u

cd "$(dirname "$0")" || exit 1

GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'; BOLD='\033[1m'; NC='\033[0m'

say()  { echo -e "${GREEN}==>${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
die()  { echo -e "${RED}ERROR:${NC} $*" >&2; exit 1; }

echo -e "${BOLD}IPI evaluation harness${NC}  (Jack Belmore, MSc dissertation)"
echo

# ---------------------------------------------------------------- prerequisites
missing=0

if ! command -v python3 >/dev/null 2>&1; then
    warn "Python 3 is not installed."
    echo "     Install it from https://www.python.org/downloads/ (3.10 or newer)."
    missing=1
fi

if ! command -v go >/dev/null 2>&1; then
    warn "Go is not installed. It is needed to build the terminal dashboard."
    echo "     Install it from https://go.dev/doc/install"
    missing=1
fi

if ! command -v ollama >/dev/null 2>&1; then
    warn "Ollama is not installed. It is what actually serves the models locally."
    echo "     Install it from https://ollama.com/download"
    missing=1
fi

[ "$missing" -eq 1 ] && die "Install the tools listed above, then run ./start.sh again."

say "python3, go and ollama are all present."

# ----------------------------------------------------------------- payloads
if [ ! -f "payloads/library.json" ]; then
    warn "No payload library at payloads/library.json."
    echo
    echo "     This repository deliberately ships without payloads. Write your own:"
    echo "     payloads/README.md documents the format, and"
    echo "     payloads/example_payload.json is a harmless file to copy and build on."
    echo
    echo -e "       ${YELLOW}cp payloads/example_payload.json payloads/library.json${NC}"
    echo
    die "Then run ./start.sh again."
fi

# ------------------------------------------------------------- python packages
if [ ! -d ".venv" ]; then
    say "Creating a Python virtual environment in .venv (one-off, a few seconds)..."
    python3 -m venv .venv || die "Could not create the virtual environment."
fi

# shellcheck disable=SC1091
source .venv/bin/activate || die "Could not activate .venv"

# Activating puts .venv/bin first on PATH, which matters because the Go dashboard
# shells out to a bare "python3" when it starts the backend.
if ! python3 -c "import requests, numpy, scipy, matplotlib" >/dev/null 2>&1; then
    say "Installing Python dependencies (requests, numpy, scipy, matplotlib)..."
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt || die "pip install failed."
fi
say "Python dependencies ready."

# ------------------------------------------------------------- test documents
# The documents are generated from payloads/library.json rather than stored, so
# that the payload text has exactly one home. This repository ships without that
# file: the payloads are yours to write.
if [ -z "$(ls -A documents/*.txt 2>/dev/null)" ]; then
    say "Generating the test documents from payloads/library.json..."
    python3 src/payload_generator.py || die "Document generation failed."
fi
say "$(ls documents/*.txt | wc -l | tr -d ' ') test documents present."

# The Quick demo in the dashboard runs against its own small set, so a first run finishes in
# minutes. It is the first two payloads in three carriers each.
if [ -z "$(ls -A documents_demo/*.txt 2>/dev/null)" ]; then
    say "Generating the small demo set..."
    python3 src/payload_generator.py --out-dir documents_demo --limit 2 \
        || die "Demo document generation failed."
fi

# -------------------------------------------------------------------- ollama
if ! curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    warn "Ollama does not seem to be running on localhost:11434."
    echo "     Open a second terminal and run:  ollama serve"
    echo "     (On macOS and Windows, starting the Ollama app does this for you.)"
    echo
    read -r -p "Press Enter once Ollama is running, or Ctrl-C to stop here. "
fi

models=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
if [ -z "$models" ]; then
    warn "Ollama is running but has no models downloaded yet."
    echo
    echo "     Pull whichever model you would like to test, for example:"
    echo -e "       ${YELLOW}ollama pull qwen2.5:7b${NC}     # about 4.7GB, the most vulnerable model I tested"
    echo -e "       ${YELLOW}ollama pull qwen3:8b${NC}       # about 5.2GB, supports the reasoning on/off toggle"
    echo -e "       ${YELLOW}ollama pull llama3.1:8b${NC}    # about 4.9GB"
    echo
    echo "     Then run ./start.sh again. Any model you pull appears in the menu automatically."
    exit 0
fi

say "Models available to test:"
echo "$models" | sed 's/^/      /'

# ------------------------------------------------------------------ dashboard
echo
say "Starting the dashboard. Pick '⚡ Quick demo' for a short run (6 documents,"
echo "    1 trial each, roughly 5 to 10 minutes). Press q to quit at any point."
echo
sleep 2

cd tui || die "Could not enter the tui directory."
exec go run .
