# =============================================================================
# Hawk-TUI Entry Point for `python -m hawk_tui`
# =============================================================================
# This module allows Hawk-TUI to be run as a Python module:
#
#   python -m hawk_tui
#
# This is equivalent to running the 'hawk-tui' command after installation.
# =============================================================================

from hawk_tui.app import main

if __name__ == "__main__":
    main()
