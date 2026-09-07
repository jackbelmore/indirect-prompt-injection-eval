package ui

import (
	"strings"
	"testing"
	"time"

	"ai-safety-tui/backend"
)

// A finished run used to call tea.Quit the moment the backend reported DoneMsg,
// which dropped the user back to the shell with no closing screen. A completed
// run and a crashed one were indistinguishable. These two tests pin the fix.

func TestDoneMsgDoesNotQuit(t *testing.T) {
	m := Model{state: stateRunning, runArgs: []string{"--output-file", "results/demo.jsonl"}}

	updated, cmd := m.Update(backend.DoneMsg{})

	got := updated.(Model)
	if got.state != stateDone {
		t.Errorf("state after DoneMsg = %v, want stateDone", got.state)
	}
	if cmd != nil {
		t.Error("DoneMsg returned a command; it must not quit, the summary has to stay on screen")
	}
}

func TestDoneViewNamesTheOutputFile(t *testing.T) {
	m := Model{
		state:   stateDone,
		runArgs: []string{"--docs-dir", "documents_demo", "--output-file", "results/demo.jsonl"},
		update:  backend.ProgressUpdate{Current: 18, Total: 18, Model: "qwen2.5:1.5b"},
	}

	view := m.doneView()

	for _, want := range []string{
		"EVALUATION COMPLETE",
		"results/demo.jsonl", // where the trials went
		"18 of 18",           // how many landed
		"analyze_results.py", // what to run next
		"qwen2.5:7b",         // why an all-zero ASR is not a failure
	} {
		if !strings.Contains(view, want) {
			t.Errorf("completion screen is missing %q", want)
		}
	}
}

func TestOutputFileFallsBackWhenNotPassed(t *testing.T) {
	m := Model{runArgs: []string{"--models", "qwen2.5:7b"}}

	if got := m.outputFile(); got != "results/audit_results.jsonl" {
		t.Errorf("outputFile() = %q, want the default results path", got)
	}
}

// classifyLog used to be three inline copies of the same if-chain. [TOOL_CALL] is not a
// prefix of [TOOL_CALL_EXPLOIT], so a chain that tests the general case first sends every
// exploiting call to UNKNOWN and renders it as a grey left-hand bubble. This pins the order.

func TestClassifyLogSeparatesExploitFromOrdinaryToolCall(t *testing.T) {
	cases := []struct {
		msg       string
		wantType  string
		wantRight bool
	}{
		{"[TOOL_CALL_EXPLOIT] safe_view_file({\"path\": \"/etc/shadow\"})", "[TOOL_CALL_EXPLOIT]", true},
		{"[TOOL_CALL] safe_view_file({\"path\": \"/docs/documents/P020_email.txt\"})", "[TOOL_CALL]", true},
		{"[OUTPUT]\nHere is the summary.", "[OUTPUT]", true},
		{"[PROMPT]\nSystem: you are helpful", "[PROMPT]", false},
		{"something else entirely", "UNKNOWN", false},
	}

	for _, c := range cases {
		gotType, gotRight := classifyLog(c.msg)
		if gotType != c.wantType || gotRight != c.wantRight {
			t.Errorf("classifyLog(%q) = %q/%v, want %q/%v",
				c.msg, gotType, gotRight, c.wantType, c.wantRight)
		}
	}
}

func TestFormatToolCallBannersAnUnauthorisedCall(t *testing.T) {
	got := formatToolCall(
		"[TOOL_CALL_EXPLOIT] safe_view_file({\"path\": \"/etc/shadow\"})\n"+
			"[TOOL_RESULT] mock stub returned; nothing was read on this machine",
		"[TOOL_CALL_EXPLOIT]")

	for _, want := range []string{"UNAUTHORISED CALL", "safe_view_file", "path: /etc/shadow", "nothing was read"} {
		if !strings.Contains(got, want) {
			t.Errorf("formatted exploit call missing %q:\n%s", want, got)
		}
	}
	if strings.Contains(got, "[TOOL_CALL_EXPLOIT]") {
		t.Errorf("prefix leaked into the bubble text:\n%s", got)
	}
}

// Go randomises map iteration and reRenderLogs redraws on every resize, so unsorted
// arguments make the lines inside a bubble shuffle while the screenshot is being framed.
func TestFormatToolCallOrdersArgumentsDeterministically(t *testing.T) {
	in := "[TOOL_CALL_EXPLOIT] safe_execute_command({\"args\": [\"-a\"], \"utility_name\": \"whoami\"})\n" +
		"[TOOL_RESULT] mock stub returned; nothing was read on this machine"

	first := formatToolCall(in, "[TOOL_CALL_EXPLOIT]")
	for i := 0; i < 50; i++ {
		if got := formatToolCall(in, "[TOOL_CALL_EXPLOIT]"); got != first {
			t.Fatalf("argument order is not stable across renders:\n%s\nvs\n%s", first, got)
		}
	}
	if !strings.Contains(first, "utility_name: whoami\n    args:") {
		t.Errorf("the attack-carrying argument should be listed first:\n%s", first)
	}
}

func TestFormatBytes(t *testing.T) {
	cases := []struct {
		in   int64
		want string
	}{
		{5033164800, "4.7GB"}, // ~ qwen2.5:7b resident
		{760 * (1 << 20), "760MB"},
		{0, "0MB"}, // the status line gates on >0, so the formatter itself need not special-case it
		{1 << 30, "1.0GB"},
	}
	for _, c := range cases {
		if got := formatBytes(c.in); got != c.want {
			t.Errorf("formatBytes(%d) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestFormatDuration(t *testing.T) {
	cases := []struct {
		in   time.Duration
		want string
	}{
		{48 * time.Second, "48s"},
		{(12*60 + 4) * time.Second, "12m 04s"},
		{(60*60 + 3*60) * time.Second, "1h 03m"},
		{0, "0s"},
		{-5 * time.Second, "0s"}, // a clock skew must not print a negative
	}
	for _, c := range cases {
		if got := formatDuration(c.in); got != c.want {
			t.Errorf("formatDuration(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestEtaString(t *testing.T) {
	// Too few trials done to estimate from.
	if got := etaString(10*time.Second, 1, 40); got != "estimating…" {
		t.Errorf("eta with 1 done = %q, want estimating…", got)
	}
	// 10 of 40 done in 60s -> 30 left should take 180s.
	if got := etaString(60*time.Second, 10, 40); got != "3m 00s" {
		t.Errorf("eta 10/40 in 60s = %q, want 3m 00s", got)
	}
	// A zero total must not divide by zero.
	if got := etaString(60*time.Second, 0, 0); got != "estimating…" {
		t.Errorf("eta with zero total = %q, want estimating…", got)
	}
	// Everything done.
	if got := etaString(60*time.Second, 40, 40); got != "done" {
		t.Errorf("eta all done = %q, want done", got)
	}
}
