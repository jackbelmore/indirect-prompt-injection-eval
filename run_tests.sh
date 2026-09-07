#!/bin/bash
#
# Everything that can be checked without a model runs first and always. The one test that
# needs Ollama serving a model is skipped, not failed, when Ollama is not there.

cd "$(dirname "$0")" || exit 1

RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
NC='\033[0m'

echo -e "${YELLOW}==============================================${NC}"
echo -e "${YELLOW}   AI Safety Dashboard - Test Harness Suite   ${NC}"
echo -e "${YELLOW}==============================================${NC}\n"

# 1. The classifier tests. These are the ones the dissertation's scoring rests on. They stub
#    out the network, so they run offline and must always pass.
echo -e "${GREEN}==> Running classifier tests (offline)...${NC}"
if ! python3 -m unittest discover -s tests -p 'test_evaluation.py' -v; then
    echo -e "\n${RED}[!] Classifier Tests Failed!${NC}"
    exit 1
fi
echo -e "${GREEN}[✓] Classifier Tests Passed!${NC}\n"

# 2. The end-to-end schema test drives a real model through the pipeline, so it needs Ollama.
echo -e "${GREEN}==> Running pipeline schema test...${NC}"
if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    if ! python3 -m pytest tests/test_pipeline_schema.py -v; then
        echo -e "\n${RED}[!] Pipeline Schema Test Failed!${NC}"
        exit 1
    fi
    echo -e "${GREEN}[✓] Pipeline Schema Test Passed!${NC}\n"
else
    echo -e "${YELLOW}[-] SKIPPED: Ollama is not running on localhost:11434.${NC}"
    echo -e "    This test needs a live model (dolphin-phi:latest by default)."
    echo -e "    Start Ollama and run again to include it.\n"
fi

# 3. The Go dashboard: it compiles, its own tests pass, and it starts and exits cleanly.
echo -e "${GREEN}==> Running Go Frontend Tests...${NC}"
cd tui || exit 1

if ! go build -o /dev/null main.go; then
    echo -e "\n${RED}[!] Go TUI Compilation Failed!${NC}"
    exit 1
fi

if ! go test ./...; then
    echo -e "\n${RED}[!] Go TUI Tests Failed!${NC}"
    exit 1
fi

if [ -f "harness.py" ]; then
    if ! python3 harness.py; then
        echo -e "\n${RED}[!] Go TUI Lifecycle Harness Failed!${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}[✓] Go Frontend Tests Passed!${NC}\n"

echo -e "${YELLOW}==============================================${NC}"
echo -e "${GREEN}  ALL TESTS PASSED. The pipeline is robust.   ${NC}"
echo -e "${YELLOW}==============================================${NC}"
