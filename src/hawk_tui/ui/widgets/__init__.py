# =============================================================================
# UI Widgets
# =============================================================================
# Reusable UI components for Hawk-TUI.
#
# These widgets are building blocks used by the screens:
#   - FolderTree: Hierarchical folder/mailbox navigation
#   - MessageList: Sortable, filterable message table
#   - MessagePreview: Rendered email content display
#   - StatusBar: Sync status and notifications
#   - CommandPalette: Quick action search (like VS Code)
# =============================================================================

from hawk_tui.ui.widgets.folder_tree import FolderTree
from hawk_tui.ui.widgets.message_list import MessageList
from hawk_tui.ui.widgets.message_preview import MessagePreview

__all__ = ["FolderTree", "MessageList", "MessagePreview"]
