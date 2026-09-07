package backend

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"

	tea "github.com/charmbracelet/bubbletea"
)

type ProgressUpdate struct {
	Type      string `json:"type"`
	Current   int    `json:"current"`
	Total     int    `json:"total"`
	Model     string `json:"model"`
	Doc       string `json:"doc"`
	Condition string `json:"condition"`
	Trial     int    `json:"trial"`
	MaxTrials int    `json:"max_trials"`
}

type ErrorUpdate struct {
	Type    string `json:"type"`
	Message string `json:"message"`
	Model   string `json:"model"`
}

type ErrorUpdateMsg ErrorUpdate

type VerboseUpdate struct {
	Type    string `json:"type"`
	Content string `json:"content"`
}

type VerboseUpdateMsg VerboseUpdate

type ProgressMsg ProgressUpdate
type DoneMsg struct{}
type ErrMsg struct{ Err error }
type PythonExitMsg struct {
	Err    error
	Stderr string
}

func FetchLocalModels() []string {
	apiURL := os.Getenv("OLLAMA_HOST")
	if apiURL == "" {
		apiURL = "http://localhost:11434"
	}
	if !strings.HasPrefix(apiURL, "http") {
		apiURL = "http://" + apiURL
	}
	apiURL = strings.TrimRight(apiURL, "/")

	resp, err := http.Get(apiURL + "/api/tags")
	if err != nil {
		return []string{"qwen2.5:7b", "qwen3:8b"}
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return []string{"qwen2.5:7b", "qwen3:8b"}
	}

	var data struct {
		Models []struct {
			Name string `json:"name"`
		} `json:"models"`
	}

	if err := json.Unmarshal(body, &data); err != nil {
		return []string{"qwen2.5:7b", "qwen3:8b"}
	}

	var models []string
	for _, m := range data.Models {
		models = append(models, m.Name)
	}

	if len(models) == 0 {
		return []string{"qwen2.5:7b", "qwen3:8b"}
	}
	return models
}

// The evaluation subprocess is tracked here so a quit from the dashboard can stop it. Without
// this, pressing q closed the UI but left python3/runner.py running against Ollama, so a long
// grid kept churning headless. The child is put in its own process group and the whole group is
// signalled, which reaches runner.py and any trial it is mid-way through but leaves ollama serve
// (a separate process) alone.
var (
	procMu      sync.Mutex
	currentProc *os.Process
)

// StopPythonBackend terminates the running evaluation subprocess, if any. Safe to call when
// nothing is running.
func StopPythonBackend() {
	procMu.Lock()
	p := currentProc
	currentProc = nil
	procMu.Unlock()
	if p == nil {
		return
	}
	// Negative pid signals the whole process group set up with Setpgid below.
	if err := syscall.Kill(-p.Pid, syscall.SIGTERM); err != nil {
		// Fall back to signalling just the child if the group send failed.
		_ = p.Signal(syscall.SIGTERM)
	}
}

func StartPythonBackend(runArgs []string, sub chan tea.Msg) tea.Cmd {
	return func() tea.Msg {
		args := []string{"src/runner.py"}
		if url := os.Getenv("OLLAMA_HOST"); url != "" {
			if !strings.HasPrefix(url, "http") {
				url = "http://" + url
			}
			url = strings.TrimRight(url, "/")
			args = append(args, "--api-url", url+"/v1")
		}
		args = append(args, runArgs...)

		cmd := exec.Command("python3", args...)
		cmd.Dir = ".."
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

		stdout, err := cmd.StdoutPipe()
		if err != nil {
			return ErrMsg{err}
		}

		var stderrBuf strings.Builder
		cmd.Stderr = &stderrBuf

		if err := cmd.Start(); err != nil {
			return ErrMsg{err}
		}
		procMu.Lock()
		currentProc = cmd.Process
		procMu.Unlock()

		go func() {
			scanner := bufio.NewScanner(stdout)
			for scanner.Scan() {
				line := scanner.Text()
				var p ProgressUpdate
				if err := json.Unmarshal([]byte(line), &p); err == nil && p.Type == "progress" {
					sub <- ProgressMsg(p)
				} else {
					var e ErrorUpdate
					if err := json.Unmarshal([]byte(line), &e); err == nil && e.Type == "error" {
						sub <- ErrorUpdateMsg(e)
					} else {
						var v VerboseUpdate
						if err := json.Unmarshal([]byte(line), &v); err == nil && v.Type == "verbose" {
							sub <- VerboseUpdateMsg(v)
						}
					}
				}
			}
			err := cmd.Wait()
			procMu.Lock()
			currentProc = nil
			procMu.Unlock()
			if err != nil {
				sub <- PythonExitMsg{Err: err, Stderr: stderrBuf.String()}
			} else {
				sub <- DoneMsg{}
			}
			close(sub)
		}()
		return nil
	}
}

func WaitForUpdate(sub chan tea.Msg) tea.Cmd {
	return func() tea.Msg {
		msg, ok := <-sub
		if !ok {
			return nil
		}
		return msg
	}
}
