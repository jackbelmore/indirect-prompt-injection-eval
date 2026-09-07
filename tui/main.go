package main

import (
	"fmt"
	"os"

	"ai-safety-tui/ui"

	tea "github.com/charmbracelet/bubbletea"
)

func main() {
	p := tea.NewProgram(
		ui.InitialModel(),
		tea.WithAltScreen(),       // Use the alternate screen buffer
		tea.WithMouseCellMotion(), // Capture mouse wheel events for scrolling
	)

	if _, err := p.Run(); err != nil {
		fmt.Printf("Error running program: %v\n", err)
		os.Exit(1)
	}
}
