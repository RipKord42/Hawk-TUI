# =============================================================================
# Hawk-TUI: A TUI Email Client with HTML Rendering
# =============================================================================
#
#   "The hawk sees all... especially your unread emails."
#
# Hawk-TUI is a terminal-based email client that renders HTML emails
# with full styling and inline images, just like a GUI client would —
# but in your terminal.
#
# Features:
#   - IMAP support with STARTTLS
#   - Full offline sync with SQLite storage
#   - HTML rendering in terminal (via Sixel/Kitty graphics)
#   - Client-side Bayesian spam filtering
#   - Reply, Reply All, Forward
#   - XDG Base Directory compliant
#
# =============================================================================

__version__ = "0.1.0"
__author__ = "Kord"
__app_name__ = "hawk-tui"

# Main entry point - this is what gets called by the 'hawk-tui' command
from hawk_tui.app import main

__all__ = ["main", "__version__", "__app_name__"]
