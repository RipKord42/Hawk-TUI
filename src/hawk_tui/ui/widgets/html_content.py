# =============================================================================
# HTML Content Widget
# =============================================================================
# Renders HTML as native Textual widgets - no images, but real scrolling
# and clickable links!
#
# This takes a different approach than text extraction or browser rendering:
# we convert HTML elements directly to Textual widgets, giving us:
#   - Native scrolling
#   - Clickable links
#   - Proper formatting
#   - All within the TUI
# =============================================================================

import re
import webbrowser
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Vertical
from textual.message import Message
from bs4 import BeautifulSoup, NavigableString, Tag

if TYPE_CHECKING:
    pass


class ClickableLink(Static):
    """A clickable link that opens in browser."""

    # Allow the widget to receive click events
    can_focus = False

    class Clicked(Message):
        """Message sent when link is clicked."""
        def __init__(self, url: str) -> None:
            self.url = url
            super().__init__()

    DEFAULT_CSS = """
    ClickableLink {
        color: $accent;
        text-style: underline;
        height: auto;
        width: auto;
    }
    ClickableLink:hover {
        color: $accent-lighten-2;
        text-style: bold underline;
        background: $surface-lighten-1;
    }
    """

    def __init__(self, text: str, url: str, **kwargs) -> None:
        # Escape Rich markup in text
        escaped_text = text.replace("[", r"\[").replace("]", r"\]")
        # Don't use [link=] tag - URLs can contain ] which breaks Rich markup
        # We handle clicks ourselves with on_click anyway
        super().__init__(f"[cyan underline]{escaped_text}[/cyan underline]", **kwargs)
        self.url = url

    def on_click(self) -> None:
        """Handle click - open URL in browser."""
        if self.url:
            webbrowser.open(self.url)
            self.app.notify(f"Opened: {self.url[:50]}...")


class HTMLContent(Vertical):
    """
    A widget that renders HTML as native Textual widgets.

    This gives us:
    - Real scrolling (it's just Textual widgets)
    - Clickable links
    - Proper text formatting
    - Native look and feel

    Usage:
        >>> content = HTMLContent()
        >>> content.render_html("<h1>Hello</h1><p>World</p>")
    """

    DEFAULT_CSS = """
    HTMLContent {
        height: auto;
        padding: 0 1;
    }

    HTMLContent > Static {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }

    HTMLContent > ClickableLink {
        margin: 0 0 1 0;
    }

    HTMLContent .h1 {
        text-style: bold;
        color: $text;
        background: $primary;
        padding: 0 1;
        margin: 1 0;
    }

    HTMLContent .h2 {
        text-style: bold;
        color: $accent;
        border-bottom: solid $accent;
        margin: 1 0 0 0;
    }

    HTMLContent .h3 {
        text-style: bold;
        color: $accent;
        margin: 1 0 0 0;
    }

    HTMLContent .blockquote {
        border-left: thick $surface-lighten-2;
        padding-left: 2;
        color: $text-muted;
        text-style: italic;
    }

    HTMLContent .code-block {
        background: $surface-darken-1;
        padding: 1;
        margin: 1 0;
    }
    """

    # Elements to skip
    SKIP_ELEMENTS = {'script', 'style', 'head', 'meta', 'link', 'noscript'}

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._widgets: list = []

    def render_html(self, html: str) -> None:
        """
        Render HTML content as Textual widgets.

        Args:
            html: HTML string to render.
        """
        # Clear existing content
        self.remove_children()
        self._widgets = []

        if not html or not html.strip():
            self.mount(Static("[dim]No content[/]"))
            return

        # Pre-clean HTML
        html = self._preclean_html(html)

        # Parse HTML
        soup = BeautifulSoup(html, "lxml")
        body = soup.body or soup

        # Convert to widgets
        self._render_element(body)

        # Mount all widgets
        if self._widgets:
            self.mount(*self._widgets)
        else:
            self.mount(Static("[dim]No content[/]"))

    def _render_element(self, element) -> None:
        """Recursively render an element."""
        if isinstance(element, NavigableString):
            text = str(element)
            # Skip pure whitespace
            if text.strip():
                # Normalize whitespace
                text = re.sub(r'\s+', ' ', text)
                # Escape Rich markup characters
                text = text.replace("[", r"\[").replace("]", r"\]")
                self._add_text(text)
            return

        if not isinstance(element, Tag):
            return

        tag = element.name.lower()

        # Skip certain elements
        if tag in self.SKIP_ELEMENTS:
            return

        # Handle specific elements
        handler = getattr(self, f'_render_{tag}', None)
        if handler:
            handler(element)
        else:
            # Default: render children
            for child in element.children:
                self._render_element(child)

    def _add_text(self, text: str) -> None:
        """Add inline text, merging with previous text widget if possible."""
        if self._widgets and isinstance(self._widgets[-1], Static):
            # Check if it's a simple text widget we can append to
            last = self._widgets[-1]
            if not hasattr(last, '_is_block'):
                # Merge text
                current = str(last.renderable) if hasattr(last, 'renderable') else ""
                last.update(current + text)
                return
        # Create new text widget
        widget = Static(text)
        self._widgets.append(widget)

    def _add_block(self, content: str, css_class: str = "", markup: bool = True) -> None:
        """Add a block-level element."""
        if not markup:
            content = content.replace("[", r"\[").replace("]", r"\]")
        # Clean up excessive newlines
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = content.strip()
        if not content:
            return
        widget = Static(content, classes=css_class)
        widget._is_block = True
        self._widgets.append(widget)

    def _get_text_content(self, element) -> str:
        """Extract text content from an element, with basic formatting."""
        parts = []
        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                text = re.sub(r'\s+', ' ', text)
                # Escape Rich markup characters
                text = text.replace("[", r"\[").replace("]", r"\]")
                parts.append(text)
            elif isinstance(child, Tag):
                tag = child.name.lower()
                inner = self._get_text_content(child)

                if tag in ('b', 'strong'):
                    parts.append(f"[bold]{inner}[/bold]")
                elif tag in ('i', 'em'):
                    parts.append(f"[italic]{inner}[/italic]")
                elif tag in ('u',):
                    parts.append(f"[underline]{inner}[/underline]")
                elif tag in ('code',):
                    parts.append(f"[on grey23 bright_green]{inner}[/]")
                elif tag == 'a':
                    href = child.get('href', '')
                    if href and not href.startswith('#'):
                        parts.append(f"[cyan underline]{inner}[/]")
                    else:
                        parts.append(inner)
                elif tag == 'br':
                    parts.append("\n")
                else:
                    parts.append(inner)

        return ''.join(parts)

    # =========================================================================
    # Element Handlers
    # =========================================================================

    def _render_p(self, element) -> None:
        """Paragraph - adds spacing between blocks."""
        content = self._get_text_content(element).strip()
        if content:
            self._add_block(content)

    def _render_div(self, element) -> None:
        """Div - treat as block container with spacing."""
        # Check if this div has meaningful text content (not just whitespace)
        has_direct_text = any(
            isinstance(c, NavigableString) and c.strip()
            for c in element.children
        )

        # If div has direct text content, render as a block
        if has_direct_text:
            content = self._get_text_content(element).strip()
            if content:
                self._add_block(content)
        else:
            # Otherwise render children recursively
            for child in element.children:
                self._render_element(child)

    def _render_span(self, element) -> None:
        """Span - inline, render children."""
        for child in element.children:
            self._render_element(child)

    def _render_br(self, element) -> None:
        """Line break."""
        self._add_text("\n")

    def _render_hr(self, element) -> None:
        """Horizontal rule."""
        self._add_block("─" * 50, css_class="hr")

    # Headings
    def _render_h1(self, element) -> None:
        content = self._get_text_content(element).strip()
        if content:
            self._add_block(f" {content} ", css_class="h1")

    def _render_h2(self, element) -> None:
        content = self._get_text_content(element).strip()
        if content:
            self._add_block(content, css_class="h2")

    def _render_h3(self, element) -> None:
        content = self._get_text_content(element).strip()
        if content:
            self._add_block(f"[bold]{content}[/]", css_class="h3")

    def _render_h4(self, element) -> None:
        content = self._get_text_content(element).strip()
        if content:
            self._add_block(f"[bold]{content}[/]")

    def _render_h5(self, element) -> None:
        self._render_h4(element)

    def _render_h6(self, element) -> None:
        self._render_h4(element)

    # Lists
    def _render_ul(self, element) -> None:
        """Unordered list."""
        for child in element.find_all('li', recursive=False):
            content = self._get_text_content(child).strip()
            if content:
                self._add_block(f"  • {content}")

    def _render_ol(self, element) -> None:
        """Ordered list."""
        for i, child in enumerate(element.find_all('li', recursive=False), 1):
            content = self._get_text_content(child).strip()
            if content:
                self._add_block(f"  {i}. {content}")

    def _render_li(self, element) -> None:
        """List item - handled by ul/ol."""
        pass

    # Links
    def _render_a(self, element) -> None:
        """Anchor/link - make it clickable!"""
        href = element.get('href', '')
        content = self._get_text_content(element).strip()

        if not content:
            return

        # Skip anchor links and empty hrefs
        if not href or href.startswith('#'):
            self._add_text(content)
            return

        # Skip tracking/long URLs - just show as styled text
        if 'tracking' in href.lower() or 'redirect' in href.lower() or len(href) > 150:
            # content is already escaped by _get_text_content
            self._add_text(f"[cyan underline]{content}[/]")
            return

        # Create clickable link widget (it handles its own escaping)
        # Need to get raw text for ClickableLink since it does its own escaping
        raw_text = element.get_text()
        raw_text = re.sub(r'\s+', ' ', raw_text).strip()
        link = ClickableLink(raw_text, href)
        self._widgets.append(link)

    # Block elements
    def _render_blockquote(self, element) -> None:
        """Blockquote."""
        content = self._get_text_content(element).strip()
        if content:
            # Add quote prefix to each line
            lines = content.split('\n')
            quoted = '\n'.join(f"│ {line}" for line in lines)
            self._add_block(f"[dim italic]{quoted}[/dim italic]", css_class="blockquote")

    def _render_pre(self, element) -> None:
        """Preformatted text."""
        # Get raw text preserving whitespace
        content = element.get_text()
        # Escape Rich markup (markup=False will also escape, but be safe)
        content = content.replace("[", r"\[").replace("]", r"\]")
        self._add_block(content, css_class="code-block", markup=False)

    def _render_code(self, element) -> None:
        """Inline code."""
        content = self._get_text_content(element)
        self._add_text(f"[on grey23 bright_green]{content}[/]")

    # Tables - email-friendly rendering
    def _render_table(self, element) -> None:
        """Table - render by traversing structure (avoid find_all which causes duplication)."""
        # Just render direct children - let tr/tbody/thead handle the rest
        for child in element.children:
            if isinstance(child, Tag):
                self._render_element(child)

    def _render_tr(self, element) -> None:
        """Table row - render each cell."""
        for child in element.children:
            if isinstance(child, Tag):
                self._render_element(child)

    def _render_td(self, element) -> None:
        """Table cell - extract content without recursing into nested tables."""
        # Check if cell has nested tables
        has_nested_table = element.find('table') is not None

        if has_nested_table:
            # Has nested table - render children to process the nested table
            for child in element.children:
                if isinstance(child, Tag):
                    self._render_element(child)
        else:
            # No nested table - just get text content
            text = self._get_text_content(element).strip()
            if text:
                self._add_block(text)

    def _render_th(self, element) -> None:
        """Table header cell - render as bold block."""
        text = self._get_text_content(element).strip()
        if text:
            self._add_block(f"[bold]{text}[/bold]")

    def _render_tbody(self, element) -> None:
        """Table body - render rows."""
        for child in element.children:
            if isinstance(child, Tag):
                self._render_element(child)

    def _render_thead(self, element) -> None:
        """Table head - render rows."""
        for child in element.children:
            if isinstance(child, Tag):
                self._render_element(child)

    # Images
    def _render_img(self, element) -> None:
        """Image - show placeholder."""
        alt = element.get('alt', '')
        if alt:
            self._add_block(f"[dim]🖼 {alt}[/]")
        else:
            self._add_block("[dim]🖼 [image][/]")

    # Semantic elements
    def _render_article(self, element) -> None:
        for child in element.children:
            self._render_element(child)

    def _render_section(self, element) -> None:
        for child in element.children:
            self._render_element(child)

    def _render_header(self, element) -> None:
        for child in element.children:
            self._render_element(child)

    def _render_footer(self, element) -> None:
        self._add_block("─" * 40)
        for child in element.children:
            self._render_element(child)

    def _render_nav(self, element) -> None:
        pass  # Skip navigation

    def _render_aside(self, element) -> None:
        for child in element.children:
            self._render_element(child)

    def _render_main(self, element) -> None:
        for child in element.children:
            self._render_element(child)

    # Formatting
    def _render_b(self, element) -> None:
        content = self._get_text_content(element)
        self._add_text(f"[bold]{content}[/bold]")

    def _render_strong(self, element) -> None:
        self._render_b(element)

    def _render_i(self, element) -> None:
        content = self._get_text_content(element)
        self._add_text(f"[italic]{content}[/italic]")

    def _render_em(self, element) -> None:
        self._render_i(element)

    def _render_u(self, element) -> None:
        content = self._get_text_content(element)
        self._add_text(f"[underline]{content}[/underline]")

    def _render_center(self, element) -> None:
        for child in element.children:
            self._render_element(child)

    def _render_font(self, element) -> None:
        for child in element.children:
            self._render_element(child)

    # =========================================================================
    # Utilities
    # =========================================================================

    def _preclean_html(self, html: str) -> str:
        """Pre-clean HTML before parsing."""
        # Remove IE conditional comments
        html = re.sub(r'<!--\[if[^\]]*\]>.*?<!\[endif\]-->', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!--\[if[^\]]*\]><!-->.*?<!--<!\[endif\]-->', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove style tags
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove script tags
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove XML/Office namespace tags
        html = re.sub(r'<\?xml[^>]*\?>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<o:[^>]*>.*?</o:[^>]*>', '', html, flags=re.DOTALL)

        return html
