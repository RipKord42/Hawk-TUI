# =============================================================================
# UI Screens
# =============================================================================
# Full-screen views for the application.
#
# Screens are the top-level containers in Textual. The app shows one screen
# at a time, and screens can be pushed/popped like a stack.
#
# Main screens:
#   - MainScreen: The default view with folder tree, message list, and preview
#   - ComposeScreen: Writing/replying to emails
#   - ReaderScreen: Full-screen message reading
#   - SettingsScreen: Account and application settings
# =============================================================================

from hawk_tui.ui.screens.main import MainScreen
from hawk_tui.ui.screens.compose import ComposeScreen
from hawk_tui.ui.screens.password import PasswordScreen

__all__ = ["MainScreen", "ComposeScreen", "PasswordScreen"]
