# =============================================================================
# Hawk-TUI Main Application
# =============================================================================
# This is the main Textual application class that orchestrates the entire UI.
#
# Textual is an async-native TUI framework that uses a CSS-like styling system.
# The application consists of:
#   - Screens: Full-window views (main, compose, settings)
#   - Widgets: Reusable UI components (folder tree, message list, etc.)
#   - Bindings: Keyboard shortcuts
#
# The app manages:
#   - Configuration loading
#   - Screen navigation
#   - Global keybindings
# =============================================================================

import argparse
import sys
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from hawk_tui import __version__, __app_name__
from hawk_tui.config import Config, ConfigError, print_paths
from hawk_tui.ui.screens.main import MainScreen


class HawkTUIApp(App):
    """
    The main Hawk-TUI application.

    This Textual App subclass is the entry point for the TUI. It manages:
        - Application lifecycle (startup, shutdown)
        - Screen navigation
        - Global keybindings

    Attributes:
        config: The loaded application configuration.
        TITLE: Window title shown in terminal.
        SUB_TITLE: Subtitle shown in header.
        CSS_PATH: Path to the Textual CSS file for styling.
        BINDINGS: Global keyboard shortcuts.
    """

    # Application metadata
    TITLE = "Hawk-TUI"
    SUB_TITLE = "Mailhawk Email"

    # Path to CSS file (relative to this module)
    CSS_PATH = Path(__file__).parent / "ui" / "styles" / "app.tcss"

    # Global keybindings - these work from any screen
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("?", "show_help", "Help"),
        Binding("c", "compose", "Compose"),
        Binding("ctrl+r", "refresh", "Sync"),
        Binding("s", "toggle_sidebar", "Sidebar", show=False),
        Binding("/", "search", "Search"),
        Binding("ctrl+s", "settings", "Settings", show=False),
    ]

    # Set MainScreen as the default screen
    SCREENS = {"main": MainScreen}

    def __init__(self, config: Config | None = None) -> None:
        """
        Initialize the Hawk-TUI application.

        Args:
            config: Optional pre-loaded configuration. If not provided,
                    configuration will be loaded from the default location.
        """
        super().__init__()

        # Initialize config error tracking
        self._config_error: str | None = None

        # Load configuration if not provided
        if config is None:
            try:
                self.config = Config.load()
            except ConfigError as e:
                self.config = Config()
                self._config_error = str(e)
        else:
            self.config = config

    async def on_mount(self) -> None:
        """Called when the application is mounted and ready."""
        # Check for config errors
        if self._config_error:
            self.notify(
                f"Config error: {self._config_error}",
                severity="error",
                timeout=10,
            )

        # Push the main screen
        await self.push_screen("main")

    # -------------------------------------------------------------------------
    # Action Handlers
    # -------------------------------------------------------------------------

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    def action_show_help(self) -> None:
        """Show the help screen."""
        self.notify(
            "Keybindings: j/k=navigate, Enter=view, r=reply, d=delete, *=star, q=quit",
            timeout=10,
        )

    def action_compose(self) -> None:
        """Open the compose screen to write a new email."""
        # Delegate to current screen's compose action if it has one
        current_screen = self.screen
        if hasattr(current_screen, "action_compose"):
            current_screen.action_compose()
        else:
            self.notify("Compose not available on this screen")

    async def action_refresh(self) -> None:
        """Trigger a manual sync of all accounts."""
        self.notify("Syncing... (background sync coming soon)")

    def action_toggle_sidebar(self) -> None:
        """Toggle the folder sidebar visibility."""
        self.notify("Toggle sidebar (not yet implemented)")

    def action_search(self) -> None:
        """Open the search dialog."""
        self.notify("Search (coming soon)")

    def action_settings(self) -> None:
        """Open the settings screen."""
        self.notify("Settings (coming soon)")


# =============================================================================
# CLI Entry Point
# =============================================================================

def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        prog=__app_name__,
        description="Hawk-TUI: A terminal email client with HTML rendering",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--paths",
        action="store_true",
        help="Print configuration paths and exit",
    )

    parser.add_argument(
        "--config",
        type=Path,
        help="Path to config file (default: XDG config location)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (verbose logging)",
    )

    return parser.parse_args()


def main() -> int:
    """
    Main entry point for Hawk-TUI.

    This function:
        1. Parses command-line arguments
        2. Handles special commands (--paths, --version)
        3. Loads configuration
        4. Starts the Textual application

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    args = parse_args()

    # Handle --paths flag
    if args.paths:
        print_paths()
        return 0

    # Load configuration
    config = None
    if args.config:
        print(f"Custom config path not yet implemented: {args.config}")
        return 1

    # Create and run the application
    app = HawkTUIApp(config=config)
    app.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
