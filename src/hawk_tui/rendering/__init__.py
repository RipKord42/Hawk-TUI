# =============================================================================
# Rendering Module
# =============================================================================
# The crown jewel of Hawk-TUI: HTML email rendering in the terminal.
#
# This module provides multiple rendering strategies:
#   - Fast mode: inscriptis-based HTML→text conversion
#   - Browser mode: Headless Chromium rendering → terminal graphics
#   - Auto mode: Tries fast first, falls back to browser for complex emails
#
# Terminal graphics support:
#   - Sixel: Widely supported, works in xterm, mlterm, etc.
#   - Kitty: Higher quality, requires Kitty terminal or compatible
#
# The rendering pipeline:
#   1. Parse HTML email
#   2. Extract and process inline images
#   3. Convert HTML to styled terminal output
#   4. Render images as terminal graphics
#   5. Compose final output for Textual display
# =============================================================================

from hawk_tui.rendering.engine import RenderEngine, RenderResult

__all__ = ["RenderEngine", "RenderResult"]
