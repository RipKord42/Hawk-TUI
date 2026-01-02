# =============================================================================
# Browser-Based HTML Rendering
# =============================================================================
# Uses a headless browser to render HTML emails with full fidelity.
#
# This is the "browser" rendering mode - slower but handles complex
# emails that break text-based rendering.
#
# Process:
#   1. Start headless Chromium via Playwright
#   2. Load HTML email content
#   3. Wait for rendering (images, fonts, etc.)
#   4. Screenshot the rendered page
#   5. Convert screenshot to terminal graphics (Sixel/Kitty)
#
# Requires: pip install playwright && playwright install chromium
# =============================================================================

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawk_tui.rendering.images import ImageDimensions


@dataclass
class BrowserRenderOptions:
    """
    Options for browser-based rendering.

    Attributes:
        viewport_width: Browser viewport width in pixels.
        viewport_height: Browser viewport height in pixels.
        wait_timeout: Max time to wait for page load (ms).
        dark_mode: Use dark background (better for terminals).
        inject_css: Additional CSS to inject.
    """
    viewport_width: int = 600      # Good width for email content
    viewport_height: int = 800
    wait_timeout: int = 10000
    dark_mode: bool = True         # Match terminal theme
    inject_css: str = ""


# Default CSS for email rendering with dark mode
DARK_MODE_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    padding: 16px;
    margin: 0;
    background-color: #1a1a1a !important;
    color: #e0e0e0 !important;
}
img { max-width: 100%; height: auto; }
a { color: #6cb6ff !important; }
table { border-collapse: collapse; max-width: 100%; }
td, th { padding: 4px 8px; }
blockquote {
    border-left: 3px solid #444;
    margin-left: 0;
    padding-left: 16px;
    color: #aaa;
}
pre, code {
    background-color: #2d2d2d;
    padding: 2px 4px;
    border-radius: 3px;
}
/* Override common email background colors */
[style*="background"] { background-color: transparent !important; }
[bgcolor] { background-color: transparent !important; }
"""


class BrowserRenderer:
    """
    Renders HTML emails using a headless browser.

    This provides pixel-perfect rendering of complex HTML emails
    at the cost of performance (starting a browser is slow).

    Usage:
        >>> async with BrowserRenderer() as renderer:
        ...     screenshot = await renderer.render(html_content)

    Note: Requires playwright to be installed:
        pip install playwright
        playwright install chromium
    """

    def __init__(self, options: BrowserRenderOptions | None = None) -> None:
        """
        Initialize the browser renderer.

        Args:
            options: Rendering options.
        """
        self.options = options or BrowserRenderOptions()
        self._browser = None
        self._playwright = None

    async def __aenter__(self) -> "BrowserRenderer":
        """Start the browser when entering context."""
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        """Stop the browser when exiting context."""
        await self.stop()

    async def start(self) -> None:
        """
        Start the headless browser.

        Call this before rendering, or use the async context manager.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Browser rendering requires playwright. "
                "Install with: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-sandbox",
            ],
        )

    async def stop(self) -> None:
        """Stop the headless browser."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def render(self, html: str) -> bytes:
        """
        Render HTML content and return a screenshot.

        Args:
            html: HTML content to render.

        Returns:
            PNG screenshot bytes.

        Raises:
            RuntimeError: If browser not started.
        """
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first or use async with.")

        # Create a new page
        page = await self._browser.new_page(
            viewport={
                "width": self.options.viewport_width,
                "height": self.options.viewport_height,
            },
        )

        try:
            # Load HTML content
            await page.set_content(html, wait_until="networkidle")

            # Inject dark mode CSS if enabled
            if self.options.dark_mode:
                await page.add_style_tag(content=DARK_MODE_CSS)

            # Inject additional custom CSS if provided
            if self.options.inject_css:
                await page.add_style_tag(content=self.options.inject_css)

            # Wait for images to load
            await page.wait_for_timeout(500)  # Small delay for any async content

            # Get the actual content height
            content_height = await page.evaluate(
                "() => document.body.scrollHeight"
            )

            # Resize viewport to fit content
            await page.set_viewport_size({
                "width": self.options.viewport_width,
                "height": min(content_height, 4000),  # Cap at 4000px
            })

            # Take screenshot
            screenshot = await page.screenshot(
                type="png",
                full_page=True,
            )

            return screenshot

        finally:
            await page.close()

    async def render_to_file(self, html: str, output_path: Path) -> None:
        """
        Render HTML and save screenshot to file.

        Args:
            html: HTML content to render.
            output_path: Path to save PNG screenshot.
        """
        screenshot = await self.render(html)
        output_path.write_bytes(screenshot)


async def is_playwright_available() -> bool:
    """
    Check if playwright is installed and has a browser.

    Returns:
        True if browser rendering is available.
    """
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            # Check if chromium is installed
            # This will fail if not installed
            browser = await p.chromium.launch(headless=True)
            await browser.close()
        return True
    except Exception:
        return False
