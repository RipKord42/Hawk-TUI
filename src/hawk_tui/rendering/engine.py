# =============================================================================
# Rendering Engine
# =============================================================================
# Coordinates HTML email rendering across different strategies.
#
# This is the main entry point for the rendering module. It:
#   - Analyzes HTML complexity to choose the best renderer
#   - Manages caching of rendered content
#   - Handles image extraction and conversion
#   - Produces Textual-compatible output
# =============================================================================

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawk_tui.core import Message
    from hawk_tui.config import RenderingConfig


class RenderMode(Enum):
    """Available rendering modes."""
    FAST = auto()       # inscriptis-based text rendering
    BROWSER = auto()    # Headless browser rendering
    AUTO = auto()       # Auto-select based on content


class ImageProtocol(Enum):
    """Terminal graphics protocols."""
    SIXEL = auto()      # Sixel graphics (widely supported)
    KITTY = auto()      # Kitty graphics protocol (high quality)
    NONE = auto()       # No image support (text only)


@dataclass
class RenderedImage:
    """
    An image rendered for terminal display.

    Attributes:
        content_id: Original Content-ID from email (for inline images).
        protocol: Graphics protocol used to render.
        data: Rendered image data (protocol-specific format).
        width: Width in terminal cells.
        height: Height in terminal cells.
        placeholder: Text placeholder for terminals without graphics.
    """
    content_id: str | None
    protocol: ImageProtocol
    data: bytes
    width: int
    height: int
    placeholder: str = "[image]"


@dataclass
class RenderResult:
    """
    Result of rendering an email.

    This contains everything needed to display the email in the TUI.

    Attributes:
        text: The rendered text content (may include Rich markup).
        images: List of rendered images with positions.
        mode_used: Which rendering mode was actually used.
        cached: Whether this result came from cache.
        error: Error message if rendering failed.
    """
    text: str
    images: list[RenderedImage] = field(default_factory=list)
    mode_used: RenderMode = RenderMode.FAST
    cached: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        """Returns True if rendering succeeded."""
        return self.error is None


class RenderEngine:
    """
    Main rendering engine for HTML emails.

    Coordinates between different rendering strategies and handles
    caching of rendered content.

    Usage:
        >>> engine = RenderEngine(config.rendering)
        >>> result = await engine.render(message)
        >>> if result.success:
        ...     display(result.text)

    Attributes:
        config: Rendering configuration.
        cache_dir: Directory for cached rendered content.
    """

    def __init__(
        self,
        config: "RenderingConfig",
        cache_dir: Path | None = None,
    ) -> None:
        """
        Initialize the rendering engine.

        Args:
            config: Rendering configuration.
            cache_dir: Directory for caching. Defaults to XDG cache.
        """
        self.config = config
        self.cache_dir = cache_dir

        # Detect terminal capabilities
        self._image_protocol = self._detect_image_protocol()

    async def render(
        self,
        message: "Message",
        *,
        force_mode: RenderMode | None = None,
    ) -> RenderResult:
        """
        Render an email message for terminal display.

        Args:
            message: Message to render.
            force_mode: Override auto-detection and use this mode.

        Returns:
            RenderResult with rendered content.
        """
        # Check cache first
        # TODO: Implement caching

        # Determine rendering mode
        if force_mode:
            mode = force_mode
        elif self.config.mode == "fast":
            mode = RenderMode.FAST
        elif self.config.mode == "browser":
            mode = RenderMode.BROWSER
        else:  # auto
            mode = self._analyze_and_choose_mode(message)

        # Render based on mode
        if mode == RenderMode.FAST:
            return await self._render_fast(message)
        else:
            return await self._render_browser(message)

    async def _render_fast(self, message: "Message") -> RenderResult:
        """
        Render using our custom HTML-to-Rich renderer.

        This mode:
            - Converts HTML to styled text with Rich markup
            - Handles headings, lists, tables, links, etc.
            - Shows image placeholders
        """
        from hawk_tui.rendering.text import TextRenderer, TextRenderOptions

        try:
            # Prefer HTML if available, fall back to plain text
            if message.body_html:
                options = TextRenderOptions(
                    display_links="inline",
                    display_images="placeholder",
                    show_link_urls=False,  # Keep it cleaner
                )
                renderer = TextRenderer(options)
                text = renderer.render(message.body_html)
                return RenderResult(text=text, mode_used=RenderMode.FAST)
            elif message.body_text:
                return RenderResult(text=message.body_text, mode_used=RenderMode.FAST)
            else:
                return RenderResult(text="[No content]", mode_used=RenderMode.FAST)
        except Exception as e:
            # Fall back to plain text on any error
            if message.body_text:
                return RenderResult(
                    text=message.body_text,
                    mode_used=RenderMode.FAST,
                    error=f"HTML rendering failed: {e}"
                )
            return RenderResult(
                text=f"[Rendering error: {e}]",
                mode_used=RenderMode.FAST,
                error=str(e)
            )

    async def _render_browser(self, message: "Message") -> RenderResult:
        """
        Render using headless browser (high-fidelity rendering).

        This mode:
            - Renders HTML in headless Chromium
            - Takes a screenshot
            - Converts screenshot to terminal graphics

        Requires playwright to be installed.
        """
        # TODO: Implement browser rendering
        # 1. Start/connect to headless browser
        # 2. Load HTML content
        # 3. Wait for rendering
        # 4. Screenshot
        # 5. Convert to Sixel/Kitty
        return RenderResult(
            text="[Browser rendering not yet implemented]",
            mode_used=RenderMode.BROWSER,
            error="Browser rendering not yet implemented",
        )

    def _analyze_and_choose_mode(self, message: "Message") -> RenderMode:
        """
        Analyze HTML complexity and choose the best rendering mode.

        Factors considered:
            - Amount of CSS
            - Complex layouts (tables, flexbox)
            - Background images
            - Custom fonts
        """
        # TODO: Implement complexity analysis
        # For now, always use fast mode
        return RenderMode.FAST

    def _detect_image_protocol(self) -> ImageProtocol:
        """
        Detect which image protocol the terminal supports.

        Checks for:
            - Kitty graphics protocol (via terminfo or direct query)
            - Sixel support (via terminfo or direct query)
        """
        # Check config override
        if self.config.image_protocol == "sixel":
            return ImageProtocol.SIXEL
        elif self.config.image_protocol == "kitty":
            return ImageProtocol.KITTY
        elif self.config.image_protocol == "none":
            return ImageProtocol.NONE

        # Auto-detect
        # TODO: Implement proper detection
        # For now, assume no image support to be safe
        return ImageProtocol.NONE

    async def clear_cache(self) -> None:
        """Clear the rendering cache."""
        # TODO: Implement cache clearing
        pass
