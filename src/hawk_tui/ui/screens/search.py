# =============================================================================
# Search Screen
# =============================================================================
# Modal dialog for searching emails.
#
# Features:
#   - Full-text search using FTS5
#   - Search within current folder or all folders
#   - Shows result count
# =============================================================================

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Static, Button, Checkbox
from textual.containers import Vertical, Horizontal


class SearchScreen(ModalScreen[tuple[str, bool] | None]):
    """
    Modal screen for entering a search query.

    Returns a tuple of (query, search_all_folders) or None if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    SearchScreen {
        align: center middle;
    }

    #search-container {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #search-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #search-input {
        margin-bottom: 1;
    }

    #search-options {
        height: auto;
        margin-bottom: 1;
    }

    #search-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #search-buttons {
        height: auto;
        align: center middle;
    }

    #search-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, current_folder_name: str = "current folder") -> None:
        """
        Initialize the search screen.

        Args:
            current_folder_name: Name of the current folder for display.
        """
        super().__init__()
        self._folder_name = current_folder_name

    def compose(self) -> ComposeResult:
        with Vertical(id="search-container"):
            yield Static("Search Messages", id="search-title")
            yield Input(
                placeholder="Enter search terms...",
                id="search-input"
            )
            with Horizontal(id="search-options"):
                yield Checkbox(
                    f"Search all folders (not just {self._folder_name})",
                    id="search-all-checkbox"
                )
            yield Static(
                "Tip: Use quotes for exact phrases, OR for alternatives",
                id="search-hint"
            )
            with Horizontal(id="search-buttons"):
                yield Button("Search", id="search-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        """Focus the search input on mount."""
        self.query_one("#search-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle enter in search input."""
        if event.input.id == "search-input":
            self._do_search()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "search-btn":
            self._do_search()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def _do_search(self) -> None:
        """Execute the search."""
        query = self.query_one("#search-input", Input).value.strip()
        if not query:
            self.notify("Please enter a search term", severity="warning")
            return

        search_all = self.query_one("#search-all-checkbox", Checkbox).value
        self.dismiss((query, search_all))

    def action_cancel(self) -> None:
        """Cancel and return None."""
        self.dismiss(None)
