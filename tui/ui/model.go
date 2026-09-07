package ui

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"

	"ai-safety-tui/backend"

	"github.com/charmbracelet/bubbles/list"
	"github.com/charmbracelet/bubbles/progress"
	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

var (
	baseStyle = lipgloss.NewStyle().Margin(0, 2)

	highlightColor = lipgloss.Color("#00E5FF") // Cyan
	accentColor    = lipgloss.Color("#7D56F4") // Royal Purple
	dimColor       = lipgloss.Color("#555555")

	titleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FFFFFF")).
			Background(accentColor).
			Padding(0, 1).
			Bold(true)

	infoStyle  = lipgloss.NewStyle().Foreground(dimColor)
	modelStyle = lipgloss.NewStyle().Foreground(highlightColor).Bold(true)
	docStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#FF2A54")).Italic(true)

	panelStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("#333333")).
			Padding(1, 2).
			MarginBottom(1)

	labelStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#777777")).Width(12)

	footerStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#626262")).MarginTop(1)

	// Status colors
	successColor = lipgloss.Color("#34C759") // Green
	warningColor = lipgloss.Color("#FF9500") // Orange
	errorColor   = lipgloss.Color("#FF3B30") // Red

)

// OllamaStatus holds the current state of the Ollama service
type OllamaStatus struct {
	IsRunning     bool
	Version       string
	RunningModels []string
	VRAMBytes     int64
	Error         string
	LastChecked   time.Time
}

// OllamaStatusMsg carries an async-fetched OllamaStatus into Update().
type OllamaStatusMsg OllamaStatus

// ollamaTickMsg triggers a periodic re-fetch of Ollama status while running.
type ollamaTickMsg struct{}

const (
	ollamaPollInterval = 4 * time.Second
	ollamaHTTPTimeout  = 1200 * time.Millisecond
)

var ollamaHTTPClient = &http.Client{Timeout: ollamaHTTPTimeout}

// fetchOllamaStatusCmd wraps getOllamaStatus in a tea.Cmd so it runs off the render path.
func fetchOllamaStatusCmd() tea.Cmd {
	return func() tea.Msg {
		return OllamaStatusMsg(getOllamaStatus(""))
	}
}

// scheduleOllamaTick schedules the next periodic Ollama status refresh.
func scheduleOllamaTick() tea.Cmd {
	return tea.Tick(ollamaPollInterval, func(time.Time) tea.Msg {
		return ollamaTickMsg{}
	})
}

// getOllamaStatus queries the Ollama API for current status
func getOllamaStatus(apiURL string) OllamaStatus {
	if apiURL == "" {
		apiURL = os.Getenv("OLLAMA_HOST")
		if apiURL == "" {
			apiURL = "http://localhost:11434"
		}
	}

	status := OllamaStatus{LastChecked: time.Now()}

	// Check version to see if Ollama is running
	resp, err := ollamaHTTPClient.Get(apiURL + "/api/version")
	if err != nil {
		status.Error = "offline"
		return status
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		status.Error = "error reading response"
		return status
	}

	var versionData struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(body, &versionData); err != nil {
		status.Error = "error parsing version"
		return status
	}

	status.IsRunning = true
	status.Version = versionData.Version

	// Get running models
	resp, err = ollamaHTTPClient.Get(apiURL + "/api/ps")
	if err == nil {
		defer resp.Body.Close()
		body, err := io.ReadAll(resp.Body)
		if err == nil {
			var psData struct {
				Models []struct {
					Name string `json:"name"`
					Size int64  `json:"size"`
					// Ollama reports resident GPU memory as size_vram; the old vram_size
					// tag never matched, so this field silently stayed zero.
					SizeVRAM int64 `json:"size_vram"`
				} `json:"models"`
			}
			if json.Unmarshal(body, &psData) == nil {
				for _, m := range psData.Models {
					status.RunningModels = append(status.RunningModels, m.Name)
					status.VRAMBytes += m.SizeVRAM
				}
			}
		}
	}

	return status
}

// formatDuration renders a duration as a short, whole-second string so the value does not
// jitter between renders: 48s, 12m 04s, 1h 03m.
func formatDuration(d time.Duration) string {
	if d < 0 {
		d = 0
	}
	total := int(d.Seconds())
	h := total / 3600
	m := (total % 3600) / 60
	sec := total % 60
	if h > 0 {
		return fmt.Sprintf("%dh %02dm", h, m)
	}
	if m > 0 {
		return fmt.Sprintf("%dm %02ds", m, sec)
	}
	return fmt.Sprintf("%ds", sec)
}

// etaString estimates the time left by linear extrapolation from the trials done so far. It
// holds off until a couple are complete, since a one-trial average is too noisy to show.
func etaString(elapsed time.Duration, current, total int) string {
	if current < 2 || total <= 0 || current >= total {
		if current >= total && total > 0 {
			return "done"
		}
		return "estimating…"
	}
	remaining := time.Duration(float64(elapsed) / float64(current) * float64(total-current))
	return formatDuration(remaining)
}

// formatBytes renders a byte count as a short GB/MB figure for the status line. Binary
// divisors, one decimal, so it lines up with how Ollama itself reports model sizes.
func formatBytes(b int64) string {
	const (
		mb = 1 << 20
		gb = 1 << 30
	)
	if b >= gb {
		return fmt.Sprintf("%.1fGB", float64(b)/gb)
	}
	return fmt.Sprintf("%.0fMB", float64(b)/mb)
}

// renderOllamaStatusLine formats the Ollama status for display
func renderOllamaStatusLine(status OllamaStatus) string {
	if !status.IsRunning {
		errMsg := "offline"
		if status.Error != "" {
			errMsg = status.Error
		}
		statusText := fmt.Sprintf("Ollama: ✗ %s", errMsg)
		return lipgloss.NewStyle().
			Foreground(errorColor).
			Render(statusText) + "\n"
	}

	runningText := "none"
	if len(status.RunningModels) > 0 {
		runningText = strings.Join(status.RunningModels[:1], ", ")
		if len(status.RunningModels) > 1 {
			runningText += fmt.Sprintf(" +%d more", len(status.RunningModels)-1)
		}
	}

	statusText := fmt.Sprintf("Ollama: ✓ v%s | Loaded: %s", status.Version, runningText)
	if status.VRAMBytes > 0 {
		statusText += fmt.Sprintf(" | VRAM: %s", formatBytes(status.VRAMBytes))
	}
	return lipgloss.NewStyle().
		Foreground(successColor).
		Render(statusText) + "\n"
}

// TrialCount holds result file trial information
type TrialCount struct {
	Model int
	Total int
}

// getTrialCountForModel counts completed trials for a specific model from result files
func getTrialCountForModel(model string) int {
	// TUI runs from tui/ directory, results are in parent dir
	resultsDir := "../results"

	// Look for result files
	files := []string{
		"audit_results.jsonl",
		"audit_results_qwen25_fixed.jsonl",
		"audit_results_qwen15b_fixed.jsonl",
		"audit_results_llama_baseline.jsonl",
		"advanced_cohort_qwen.jsonl",
		"advanced_cohort_llama.jsonl",
		"advanced_cohort_wave2.jsonl",
		"advanced_cohort_wave3.jsonl",
	}

	trialCount := 0
	seenTrials := make(map[string]bool)

	for _, fname := range files {
		fpath := fmt.Sprintf("%s/%s", resultsDir, fname)
		file, err := os.Open(fpath)
		if err != nil {
			continue // File doesn't exist, skip
		}
		defer file.Close()

		scanner := bufio.NewScanner(file)
		for scanner.Scan() {
			line := scanner.Text()
			var trial struct {
				Model        string `json:"model"`
				Condition    string `json:"condition"`
				DocumentName string `json:"document_name"`
				TrialIndex   int    `json:"trial_index"`
				Status       string `json:"status"`
			}

			if err := json.Unmarshal([]byte(line), &trial); err != nil {
				continue
			}

			// Handle renamed model tags
			modelCheck := trial.Model
			if modelCheck == "qwen2.5:7b-tools" {
				modelCheck = "qwen2.5:7b"
			} else if modelCheck == "llama3.1:8b-tools" {
				modelCheck = "llama3.1:8b"
			}

			if modelCheck == model && trial.Status != "error" {
				// Create unique key to avoid double-counting across files
				key := fmt.Sprintf("%s_%s_%s_%d", model, trial.Condition, trial.DocumentName, trial.TrialIndex)
				if !seenTrials[key] {
					seenTrials[key] = true
					trialCount++
				}
			}
		}
	}

	return trialCount
}

// classifyLog maps a verbose line to its bubble type and which side it sits on. Three copies
// of this used to sit inline in Update and reRenderLogs; keeping it in one place is what stops
// a new prefix from being handled in two of them and missed in the third.
//
// [TOOL_CALL_EXPLOIT] is tested first: "[TOOL_CALL]" is not a prefix of it, so the general
// case cannot stand in for the specific one.
func classifyLog(msg string) (logType string, isRight bool) {
	switch {
	case strings.HasPrefix(msg, "[TOOL_CALL_EXPLOIT]"):
		return "[TOOL_CALL_EXPLOIT]", true
	case strings.HasPrefix(msg, "[TOOL_CALL]"):
		return "[TOOL_CALL]", true
	case strings.HasPrefix(msg, "[OUTPUT]"):
		return "[OUTPUT]", true
	case strings.HasPrefix(msg, "[PROMPT]"):
		return "[PROMPT]", false
	}
	return "UNKNOWN", false
}

// argOrder sorts a call's arguments for display. Go randomises map iteration, and
// reRenderLogs redraws every bubble on a window resize, so an unsorted map makes the lines
// inside a bubble shuffle while you are looking at it. The argument that carries the attack
// is promoted to the top so it is the first thing read.
func argOrder(args map[string]interface{}) []string {
	keys := make([]string, 0, len(args))
	for k := range args {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		rank := func(k string) int {
			if k == "path" || k == "utility_name" {
				return 0
			}
			return 1
		}
		if rank(keys[i]) != rank(keys[j]) {
			return rank(keys[i]) < rank(keys[j])
		}
		return keys[i] < keys[j]
	})
	return keys
}

// formatToolCall turns "[TOOL_CALL] func_name({json})\n[TOOL_RESULT] result" into something
// readable at a glance: the tool on one line, each argument indented under it, the result last.
func formatToolCall(toolCallText string, logType string) string {
	parts := strings.Split(toolCallText, "\n[TOOL_RESULT]")
	if len(parts) < 1 {
		return toolCallText
	}

	isExploit := logType == "[TOOL_CALL_EXPLOIT]"
	callPart := strings.TrimPrefix(parts[0], "[TOOL_CALL_EXPLOIT] ")
	callPart = strings.TrimPrefix(callPart, "[TOOL_CALL] ")

	resultPart := ""
	if len(parts) > 1 {
		resultPart = strings.TrimSpace(parts[1])
	}

	funcName := callPart
	argsStr := ""
	if idx := strings.Index(callPart, "("); idx != -1 && strings.HasSuffix(callPart, ")") {
		funcName = callPart[:idx]
		argsStr = callPart[idx+1 : len(callPart)-1]
	}

	var sb strings.Builder
	if isExploit {
		sb.WriteString("⚠ UNAUTHORISED CALL\n")
	}
	sb.WriteString("• " + funcName)

	if argsStr != "" {
		var args map[string]interface{}
		if err := json.Unmarshal([]byte(argsStr), &args); err == nil && len(args) > 0 {
			for _, k := range argOrder(args) {
				sb.WriteString(fmt.Sprintf("\n    %s: %v", k, args[k]))
			}
		} else {
			sb.WriteString(fmt.Sprintf("\n    %s", argsStr))
		}
	}

	if resultPart != "" && resultPart != "None" {
		sb.WriteString(fmt.Sprintf("\n  → %s", resultPart))
	}
	return sb.String()
}

func (m Model) renderBubble(text string, logType string, isStacked bool) string {
	width := m.progress.Width
	if width < 40 {
		width = 80 // fallback
	}

	bubbleWidth := int(float64(width) * 0.75)

	var bg lipgloss.Color
	fg := lipgloss.Color("#FFFFFF")
	isRight := false

	switch logType {
	case "[PROMPT]":
		bg = lipgloss.Color("#E9E9EB") // Apple Light Gray
		fg = lipgloss.Color("#000000") // Black text
	case "[OUTPUT]":
		bg = lipgloss.Color("#007AFF") // Apple Blue (sent message)
		isRight = true
	case "[TOOL_CALL]":
		bg = lipgloss.Color("#34C759") // Apple Green
		isRight = true
		// Format tool call nicely
		text = formatToolCall(text, logType)
	case "[TOOL_CALL_EXPLOIT]":
		// Red is reserved for a call the trial's own classifier scores as unauthorised. The
		// predicate lives in evaluation_pipeline.is_exploiting_call and is the same one the
		// recorded status comes from, so the colour cannot contradict the logged outcome.
		bg = errorColor
		isRight = true
		text = formatToolCall(text, logType)
	default:
		bg = lipgloss.Color("#E9E9EB")
		fg = lipgloss.Color("#000000")
	}

	border := lipgloss.RoundedBorder()
	if isStacked {
		border = lipgloss.Border{
			Top:         "─",
			Bottom:      "─",
			Left:        "│",
			Right:       "│",
			TopLeft:     "┌",
			TopRight:    "┐",
			BottomLeft:  "╰",
			BottomRight: "╯",
		}
	}

	bStyle := lipgloss.NewStyle().
		Border(border).
		BorderForeground(bg).
		Background(bg).
		Foreground(fg).
		Padding(0, 2). // Generous horizontal padding
		Width(bubbleWidth)

	rendered := bStyle.Render(text)

	if isRight {
		return lipgloss.PlaceHorizontal(width, lipgloss.Right, rendered)
	}
	return lipgloss.PlaceHorizontal(width, lipgloss.Left, rendered)
}

type sessionState int

const (
	stateMenu sessionState = iota
	stateRunning
	stateDone
)

type item struct {
	title, desc string
	args        []string
}

func (i item) Title() string       { return i.title }
func (i item) Description() string { return i.desc }
func (i item) FilterValue() string { return i.title }

type Model struct {
	state        sessionState
	list         list.Model
	spinner      spinner.Model
	progress     progress.Model
	err          error
	done         bool
	update       backend.ProgressUpdate
	sub          chan tea.Msg
	exited       bool
	runArgs      []string
	verboseLogs  []string
	renderedLogs []string
	vp           viewport.Model
	ready        bool
	ollamaStatus OllamaStatus
	startTime    time.Time
}

func (m *Model) reRenderLogs() {
	m.renderedLogs = nil
	var prevIsRight *bool

	for _, logMsg := range m.verboseLogs {
		logType, isRight := classifyLog(logMsg)

		isStacked := false
		if prevIsRight != nil {
			if *prevIsRight == isRight {
				isStacked = true
			} else {
				m.renderedLogs = append(m.renderedLogs, "")
			}
		}

		m.renderedLogs = append(m.renderedLogs, m.renderBubble(logMsg, logType, isStacked))

		currentIsRight := isRight
		prevIsRight = &currentIsRight
	}
	m.vp.SetContent(strings.Join(m.renderedLogs, "\n"))
}

func InitialModel() Model {
	availableModels := backend.FetchLocalModels()
	var items []list.Item

	allModelsArgs := []string{"--models"}
	allModelsArgs = append(allModelsArgs, availableModels...)

	// Quick demo runs first: 6 documents x 1 trial instead of the full 93-document grid, so a
	// first-time user gets a complete result in minutes rather than hours. Writes to its own
	// output file so a demo can never contaminate the real audit log.
	for _, m := range availableModels {
		items = append(items, item{
			title: fmt.Sprintf("⚡ Quick demo — %s", m),
			desc:  fmt.Sprintf("6 documents, 1 trial each (~5-10 min). Results go to results/demo.jsonl"),
			args: []string{
				"--models", m,
				"--trials", "1",
				"--docs-dir", "documents_demo",
				"--output-file", "results/demo.jsonl",
				"--verbose",
			},
		})
	}

	items = append(items, item{
		title: "▶ Resume All Local Models",
		desc:  fmt.Sprintf("Resume evaluation for: %s", strings.Join(availableModels, ", ")),
		args:  allModelsArgs,
	})

	items = append(items, item{
		title: "⚠ Force Restart All",
		desc:  "Clear cache and force re-evaluate all local models",
		args:  append(allModelsArgs, "--force"),
	})

	for _, m := range availableModels {
		// Get trial count for this model
		trialCount := getTrialCountForModel(m)
		trialCountStr := ""
		if trialCount > 0 {
			trialCountStr = fmt.Sprintf(" | %d trials completed", trialCount)
		}

		items = append(items, item{
			title: fmt.Sprintf("Run %s", m),
			desc:  fmt.Sprintf("Resume evaluation only for %s%s", m, trialCountStr),
			args:  []string{"--models", m},
		})
		items = append(items, item{
			title: fmt.Sprintf("Run %s (Verbose)", m),
			desc:  fmt.Sprintf("Resume evaluation only for %s with live logs%s", m, trialCountStr),
			args:  []string{"--models", m, "--verbose"},
		})
		items = append(items, item{
			title: fmt.Sprintf("Force Restart %s", m),
			desc:  fmt.Sprintf("Clear cache and evaluate %s (currently %d trials)%s", m, trialCount, trialCountStr),
			args:  []string{"--models", m, "--force"},
		})
	}

	l := list.New(items, list.NewDefaultDelegate(), 0, 0)
	l.Title = "Select Run Profile"
	l.SetShowStatusBar(true)
	l.SetFilteringEnabled(true)
	l.FilterInput.Placeholder = "Filter (press / to search)"
	l.KeyMap.Filter.SetKeys("/")

	p := progress.New(
		progress.WithGradient("#00F2FE", "#4FACFE"),
	)
	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = lipgloss.NewStyle().Foreground(highlightColor)

	return Model{
		state:    stateMenu,
		list:     l,
		spinner:  s,
		progress: p,
		sub:      make(chan tea.Msg),
	}
}

func (m Model) Init() tea.Cmd {
	return nil
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		if m.state == stateMenu {
			height := msg.Height
			if height > 15 {
				height = 15
			}
			m.list.SetSize(msg.Width, height)
		}
		m.progress.Width = msg.Width - 4

		// Fixed chrome outside the viewport: header(1) + ollama status(2) + running
		// panel border/padding/content(12) + "LIVE LOGS" blank+title(2) + footer(1) +
		// baseStyle top/bottom margin(2) = 20 lines, plus a small safety margin since
		// exact wrapped-line counts can vary slightly with terminal width/content.
		vpHeight := msg.Height - 24
		if vpHeight < 5 {
			vpHeight = 5
		}
		if !m.ready {
			m.vp = viewport.New(msg.Width, vpHeight)
			m.ready = true
		} else {
			m.vp.Width = msg.Width
			m.vp.Height = vpHeight
		}

		if m.state == stateRunning {
			m.reRenderLogs()
		}
	case tea.KeyMsg:
		if msg.String() == "ctrl+c" {
			backend.StopPythonBackend()
			return m, tea.Quit
		}

		if m.state == stateMenu {
			// Only quit on 'q' if not actively filtering (FilterState == 0 means no filter)
			if msg.String() == "q" && m.list.FilterState() == 0 {
				return m, tea.Quit
			}

			if msg.String() == "enter" {
				i, ok := m.list.SelectedItem().(item)
				if ok {
					m.runArgs = i.args
					m.state = stateRunning
					m.ollamaStatus = OllamaStatus{Error: "checking...", LastChecked: time.Now()}
					return m, tea.Batch(
						m.spinner.Tick,
						backend.StartPythonBackend(m.runArgs, m.sub),
						backend.WaitForUpdate(m.sub),
						fetchOllamaStatusCmd(),
						scheduleOllamaTick(),
					)
				}
			}

			// Let the list handle filtering and other inputs
			var cmd tea.Cmd
			m.list, cmd = m.list.Update(msg)
			return m, cmd
		} else if m.state == stateDone {
			// Any of the usual exit keys leaves the summary. Scrolling still works
			// so the logs can be read back before quitting.
			switch msg.String() {
			case "q", "enter", "esc":
				backend.StopPythonBackend()
				return m, tea.Quit
			}
			if m.ready {
				var cmd tea.Cmd
				m.vp, cmd = m.vp.Update(msg)
				return m, cmd
			}
		} else if m.state == stateRunning {
			// Allow 'q' to quit even in verbose/running mode. Stop the evaluation
			// subprocess first, otherwise it keeps running headless after the UI closes.
			if msg.String() == "q" {
				backend.StopPythonBackend()
				return m, tea.Quit
			}

			if m.ready {
				var cmd tea.Cmd
				m.vp, cmd = m.vp.Update(msg)
				return m, cmd
			}
		}

	case tea.MouseMsg:
		if m.state == stateRunning && m.ready {
			var cmd tea.Cmd
			m.vp, cmd = m.vp.Update(msg)
			return m, cmd
		}

	case backend.ErrorUpdateMsg:
		m.err = fmt.Errorf("Evaluation Error for %s:\n%s", msg.Model, msg.Message)
		return m, nil
	case backend.PythonExitMsg:
		m.err = fmt.Errorf("Python crashed: %v\n\nStderr:\n%s", msg.Err, msg.Stderr)
		return m, nil
	case backend.ErrMsg:
		m.err = msg.Err
		return m, nil
	case backend.DoneMsg:
		// Deliberately does not quit. Quitting here dropped the user straight back
		// to the shell with no closing screen, which reads as a crash -- the run
		// looks identical whether it finished or died. Hold on the summary until a
		// key is pressed instead.
		m.done = true
		m.exited = true
		m.state = stateDone
		return m, nil
	case backend.VerboseUpdateMsg:
		m.verboseLogs = append(m.verboseLogs, msg.Content)

		logType, isRight := classifyLog(msg.Content)

		isStacked := false
		if len(m.verboseLogs) > 1 {
			prevMsg := m.verboseLogs[len(m.verboseLogs)-2]
			_, prevIsRight := classifyLog(prevMsg)
			if prevIsRight == isRight {
				isStacked = true
			} else {
				m.renderedLogs = append(m.renderedLogs, "")
			}
		}

		m.renderedLogs = append(m.renderedLogs, m.renderBubble(msg.Content, logType, isStacked))

		wasAtBottom := m.vp.AtBottom() || m.vp.TotalLineCount() == 0
		m.vp.SetContent(strings.Join(m.renderedLogs, "\n"))
		if wasAtBottom {
			m.vp.GotoBottom()
		}

		return m, backend.WaitForUpdate(m.sub)
	case backend.ProgressMsg:
		// The first progress update is the true start of the run. Timing from here keeps
		// venv setup and the initial model load out of the elapsed figure and the ETA.
		if m.startTime.IsZero() {
			m.startTime = time.Now()
		}
		m.update = backend.ProgressUpdate(msg)
		var percent float64
		if m.update.Total > 0 {
			percent = float64(m.update.Current) / float64(m.update.Total)
		}
		if percent > 1.0 {
			percent = 1.0
		}
		m.progress.SetPercent(percent)
		return m, backend.WaitForUpdate(m.sub)
	case spinner.TickMsg:
		if m.state == stateRunning {
			var cmd tea.Cmd
			m.spinner, cmd = m.spinner.Update(msg)
			return m, cmd
		}
	case progress.FrameMsg:
		if m.state == stateRunning {
			progressModel, cmd := m.progress.Update(msg)
			m.progress = progressModel.(progress.Model)
			return m, cmd
		}
	case ollamaTickMsg:
		if m.state == stateRunning && !m.exited && m.err == nil {
			return m, tea.Batch(fetchOllamaStatusCmd(), scheduleOllamaTick())
		}
		return m, nil
	case OllamaStatusMsg:
		m.ollamaStatus = OllamaStatus(msg)
		return m, nil
	}

	if m.state == stateMenu {
		var cmd tea.Cmd
		m.list, cmd = m.list.Update(msg)
		return m, cmd
	}

	return m, nil
}

// outputFile digs the --output-file value back out of the args the menu entry was
// built with, so the summary can name the file the trials actually landed in.
func (m Model) outputFile() string {
	for i, a := range m.runArgs {
		if a == "--output-file" && i+1 < len(m.runArgs) {
			return m.runArgs[i+1]
		}
	}
	return "results/audit_results.jsonl"
}

// doneView is the screen the run ends on. It stays up until a key is pressed:
// the previous behaviour quit immediately, so a completed run and a crashed one
// looked exactly the same from the shell.
func (m Model) doneView() string {
	out := m.outputFile()

	var sb strings.Builder
	sb.WriteString(titleStyle.Render("EVALUATION COMPLETE") + "\n\n")

	if m.update.Total > 0 {
		sb.WriteString(fmt.Sprintf("%s%s\n",
			labelStyle.Render("Trials:"),
			infoStyle.Render(fmt.Sprintf("%d of %d completed", m.update.Current, m.update.Total))))
	}
	if m.update.Model != "" {
		sb.WriteString(fmt.Sprintf("%s%s\n", labelStyle.Render("Model:"), modelStyle.Render(m.update.Model)))
	}
	if !m.startTime.IsZero() {
		sb.WriteString(fmt.Sprintf("%s%s\n", labelStyle.Render("Total time:"), infoStyle.Render(formatDuration(time.Since(m.startTime)))))
	}
	sb.WriteString(fmt.Sprintf("%s%s\n", labelStyle.Render("Written to:"), docStyle.Render(out)))

	sb.WriteString("\n" + infoStyle.Render("Nothing is committed or uploaded. The file above is the whole result.") + "\n")

	// Plain, not labelStyle: that style is width-padded for the aligned rows above
	// and wraps a heading this long onto two lines.
	sb.WriteString("\nSee the breakdown:\n")
	sb.WriteString(fmt.Sprintf("  python3 src/analyze_results.py --results %s --csv\n", out))

	sb.WriteString("\n" + infoStyle.Render(
		"An Attack Success Rate of 0.0% everywhere is a normal result for a small\n"+
			"model. Models below about 7B often will not make tool calls at all, so\n"+
			"there is nothing for a payload to hijack. Try qwen2.5:7b to see exploits.") + "\n")

	sb.WriteString("\n" + footerStyle.Render("q or enter to quit • ↑/↓ to scroll the logs"))

	return baseStyle.Render(sb.String())
}

func (m Model) View() string {
	if m.err != nil {
		return fmt.Sprintf("\n%s\n\n%s\n\nPress 'q' to quit.",
			titleStyle.Render("ERROR FATAL"),
			m.err)
	}

	if m.state == stateMenu {
		return m.list.View()
	}

	if m.state == stateDone {
		return m.doneView()
	}

	var sb strings.Builder

	headerWidth := m.progress.Width + 4
	if headerWidth < 40 {
		headerWidth = 80
	}
	header := lipgloss.PlaceHorizontal(headerWidth, lipgloss.Center, titleStyle.Render("AI SAFETY RED TEAMING DASHBOARD"))
	sb.WriteString(header + "\n")

	// Add Ollama status line (value is refreshed asynchronously; View() only reads the cache)
	statusLine := renderOllamaStatusLine(m.ollamaStatus)
	sb.WriteString(statusLine)

	panelContentWidth := m.progress.Width
	if panelContentWidth < 40 {
		panelContentWidth = 76
	}
	currentPanelStyle := panelStyle.Copy().Width(panelContentWidth)

	if m.update.Total == 0 {
		panelContent := fmt.Sprintf("%s Initializing evaluation pipeline...", m.spinner.View())
		sb.WriteString(currentPanelStyle.Render(panelContent))
	} else {
		var pSb strings.Builder
		pSb.WriteString(m.progress.View() + "\n")
		pSb.WriteString(fmt.Sprintf("%s Running trial %d/%d\n", m.spinner.View(), m.update.Trial, m.update.MaxTrials))

		pSb.WriteString(fmt.Sprintf("%s%s\n", labelStyle.Render("Model:"), modelStyle.Render(m.update.Model)))
		pSb.WriteString(fmt.Sprintf("%s%s\n", labelStyle.Render("Document:"), docStyle.Render(m.update.Doc)))
		pSb.WriteString(fmt.Sprintf("%s%s\n", labelStyle.Render("Condition:"), infoStyle.Render(m.update.Condition)))
		pSb.WriteString(fmt.Sprintf("%s%d / %d completed\n", labelStyle.Render("Overall:"), m.update.Current, m.update.Total))

		if !m.startTime.IsZero() {
			elapsed := time.Since(m.startTime)
			pSb.WriteString(fmt.Sprintf("%s%s\n", labelStyle.Render("Elapsed:"), infoStyle.Render(formatDuration(elapsed))))
			pSb.WriteString(fmt.Sprintf("%s%s", labelStyle.Render("ETA:"), infoStyle.Render(etaString(elapsed, m.update.Current, m.update.Total))))
		}

		// The Ollama status line at the top scrolls off a short terminal, so the VRAM figure is
		// repeated here in the panel where it stays visible. Shown only once the poll has found
		// a resident model.
		if m.ollamaStatus.VRAMBytes > 0 {
			pSb.WriteString(fmt.Sprintf("\n%s%s", labelStyle.Render("GPU VRAM:"), infoStyle.Render(formatBytes(m.ollamaStatus.VRAMBytes))))
		}

		sb.WriteString(currentPanelStyle.Render(pSb.String()))
	}

	if len(m.verboseLogs) > 0 {
		sb.WriteString("\n\n" + titleStyle.Render("LIVE LOGS"))
		sb.WriteString("\n" + m.vp.View())
	}

	sb.WriteString("\n" + footerStyle.Render("q quit • ctrl+c force quit"))

	return baseStyle.Render(sb.String())
}
