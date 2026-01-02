# =============================================================================
# UI Module
# =============================================================================
# Textual-based user interface for Hawk-TUI.
#
# Structure:
#   - screens/: Full-screen views (main, compose, settings, etc.)
#   - widgets/: Reusable UI components (folder tree, message list, etc.)
#   - styles/: Textual CSS files for styling
#
# Textual is a modern TUI framework that uses:
#   - CSS-like styling (.tcss files)
#   - Reactive programming (watchers, bindings)
#   - Async-native design (works well with async IMAP/storage)
# =============================================================================

# Screen exports
from hawk_tui.ui.screens.main import MainScreen
from hawk_tui.ui.screens.compose import ComposeScreen

# Widget exports
from hawk_tui.ui.widgets.folder_tree import FolderTree
from hawk_tui.ui.widgets.message_list import MessageList
from hawk_tui.ui.widgets.message_preview import MessagePreview

__all__ = [
    "MainScreen",
    "ComposeScreen",
    "FolderTree",
    "MessageList",
    "MessagePreview",
]
