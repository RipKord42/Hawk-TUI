# =============================================================================
# File Picker Screen
# =============================================================================
# A simple file browser for selecting files to attach.
#
# Features:
#   - Navigate directories with keyboard
#   - Filter by extension
#   - Show file sizes
#   - Quick path input
# =============================================================================

from pathlib import Path
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Input, Static, Button
from textual.containers import Vertical, Horizontal


class FilePickerScreen(ModalScreen[str | None]):
    """
    Modal screen for picking a file.

    Returns the selected file path, or None if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "select", "Select"),
    ]

    CSS = """
    FilePickerScreen {
        align: center middle;
    }

    #file-picker-container {
        width: 80%;
        height: 80%;
        min-width: 60;
        min-height: 20;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }

    #file-picker-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #path-input {
        margin-bottom: 1;
    }

    #directory-tree {
        height: 1fr;
        border: tall $primary;
    }

    #file-info {
        height: 2;
        margin-top: 1;
        color: $text-muted;
    }

    #file-picker-buttons {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    #file-picker-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, start_path: str | None = None) -> None:
        """
        Initialize the file picker.

        Args:
            start_path: Starting directory path. Defaults to home.
        """
        super().__init__()
        if start_path:
            self._start_path = Path(start_path).expanduser()
        else:
            self._start_path = Path.home()
        self._selected_path: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="file-picker-container"):
            yield Static("Select File to Attach", id="file-picker-title")
            yield Input(
                value=str(self._start_path),
                placeholder="Enter path or browse below",
                id="path-input"
            )
            yield DirectoryTree(str(self._start_path), id="directory-tree")
            yield Static("Select a file", id="file-info")
            with Horizontal(id="file-picker-buttons"):
                yield Button("Attach", id="attach-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        """Focus the directory tree on mount."""
        tree = self.query_one("#directory-tree", DirectoryTree)
        tree.focus()

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        """Handle file selection in directory tree."""
        self._selected_path = event.path
        self._update_file_info(event.path)

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Handle directory selection - update path input."""
        path_input = self.query_one("#path-input", Input)
        path_input.value = str(event.path)

    def _update_file_info(self, path: Path) -> None:
        """Update the file info display."""
        try:
            stat = path.stat()
            size = stat.st_size
            # Human-readable size
            for unit in ("B", "KB", "MB", "GB"):
                if size < 1024:
                    size_str = f"{size:.1f} {unit}" if size != int(size) else f"{int(size)} {unit}"
                    break
                size /= 1024
            else:
                size_str = f"{size:.1f} TB"

            info = f"Selected: {path.name} ({size_str})"
            info_widget = self.query_one("#file-info", Static)
            info_widget.update(info)
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle path input submission."""
        if event.input.id == "path-input":
            path = Path(event.value).expanduser()
            if path.is_file():
                self._selected_path = path
                self._update_file_info(path)
                self.dismiss(str(path))
            elif path.is_dir():
                # Navigate to directory
                tree = self.query_one("#directory-tree", DirectoryTree)
                tree.path = path
                tree.reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "attach-btn":
            self.action_select()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def action_select(self) -> None:
        """Select the current file and return."""
        # First check if there's a path in the input
        path_input = self.query_one("#path-input", Input)
        input_path = Path(path_input.value).expanduser()

        if input_path.is_file():
            self.dismiss(str(input_path))
        elif self._selected_path and self._selected_path.is_file():
            self.dismiss(str(self._selected_path))
        else:
            self.notify("Please select a file", severity="warning")

    def action_cancel(self) -> None:
        """Cancel and return None."""
        self.dismiss(None)
