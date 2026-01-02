# =============================================================================
# Text-Based HTML Rendering
# =============================================================================
# Converts HTML emails to styled terminal text using inscriptis.
#
# inscriptis is a battle-tested HTML-to-text converter that handles:
#   - Complex table layouts (common in email HTML)
#   - Proper whitespace and line break handling
#   - Lists, headings, and other semantic elements
#
# We add Rich markup on top for terminal styling.
# =============================================================================

from dataclasses import dataclass
from typing import TYPE_CHECKING
import re

from inscriptis import get_text
from inscriptis.model.config import ParserConfig
from inscriptis.css_profiles import CSS_PROFILES

if TYPE_CHECKING:
    pass


@dataclass
class TextRenderOptions:
    """
    Options for text rendering.

    Attributes:
        display_links: How to handle links ("inline", "footnote", "hide").
        display_images: How to handle images ("placeholder", "alt_text", "hide").
        max_width: Maximum line width (0 = no limit).
        preserve_formatting: Preserve whitespace formatting.
        show_link_urls: Show URLs after link text.
    """
    display_links: str = "inline"       # Show [text](url) inline
    display_images: str = "placeholder" # Show [image: alt_text]
    max_width: int = 0                  # 0 = no limit
    preserve_formatting: bool = True
    show_link_urls: bool = True         # Show URLs after link text


class TextRenderer:
    """
    Renders HTML to styled terminal text using inscriptis.

    inscriptis is a battle-tested HTML-to-text converter that handles
    complex email HTML including table layouts, lists, and semantic elements.

    Usage:
        >>> renderer = TextRenderer()
        >>> text = renderer.render(html_content)
    """

    def __init__(self, options: TextRenderOptions | None = None) -> None:
        """
        Initialize the text renderer.

        Args:
            options: Rendering options.
        """
        self.options = options or TextRenderOptions()

        # Configure inscriptis
        self._config = ParserConfig(
            css=CSS_PROFILES['strict'],  # Better whitespace handling
            display_links=self.options.display_links != "hide",
            display_images=self.options.display_images != "hide",
            display_anchors=False,  # Don't show anchor names
        )

    def render(self, html_content: str) -> str:
        """
        Convert HTML to styled terminal text.

        Args:
            html_content: HTML content to render.

        Returns:
            Plain text (inscriptis doesn't do Rich markup, but it handles
            structure well).
        """
        if not html_content or not html_content.strip():
            return ""

        # Pre-clean HTML
        html_content = self._preclean_html(html_content)

        # Use inscriptis for conversion
        text = get_text(html_content, self._config)

        # Post-process
        text = self._clean_output(text)

        # Escape Rich markup characters in the output
        text = text.replace('[', r'\[')

        return text

    def _preclean_html(self, html: str) -> str:
        """Pre-clean HTML before parsing to remove problematic content."""
        # Remove IE conditional comments
        html = re.sub(r'<!--\[if[^\]]*\]>.*?<!\[endif\]-->', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!--\[if[^\]]*\]><!-->.*?<!--<!\[endif\]-->', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!\[if[^\]]*\]>.*?<!\[endif\]>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove MSO (Microsoft Office) comments
        html = re.sub(r'<!--\[if gte mso.*?<!\[endif\]-->', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove style tags
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove script tags (shouldn't be in email but just in case)
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove XML/Office namespace tags
        html = re.sub(r'<\?xml[^>]*\?>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<o:[^>]*>.*?</o:[^>]*>', '', html, flags=re.DOTALL)
        html = re.sub(r'<v:[^>]*>.*?</v:[^>]*>', '', html, flags=re.DOTALL)

        return html

    def _clean_output(self, text: str) -> str:
        """Clean up the rendered output."""
        # Remove zero-width characters
        text = re.sub(r'[\u200b\u200c\u200d\u2060\ufeff]+', '', text)

        # Normalize multiple blank lines to max 2
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Remove trailing whitespace from lines
        lines = text.split('\n')
        lines = [line.rstrip() for line in lines]
        text = '\n'.join(lines)

        # Remove leading/trailing blank lines
        text = text.strip()

        return text

    def extract_images(self, html_content: str) -> list[dict]:
        """
        Extract image references from HTML.

        Returns a list of dicts with:
            - src: Image source (URL or cid:content_id)
            - alt: Alt text
            - is_inline: True if src starts with "cid:"

        These can be used to fetch and render images separately.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "lxml")
        images = []

        for img in soup.find_all("img"):
            src = img.get("src", "")
            images.append({
                "src": src,
                "alt": img.get("alt", ""),
                "is_inline": src.startswith("cid:"),
            })

        return images
