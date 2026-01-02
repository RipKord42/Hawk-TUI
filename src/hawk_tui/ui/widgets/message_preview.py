# =============================================================================
# Message Preview Widget
# =============================================================================
# Displays rendered email content.
#
# This is where the magic happens - HTML emails are rendered here
# using the rendering engine.
#
# Features:
#   - Renders HTML emails as native Textual widgets
#   - Clickable links that open in browser
#   - Native scrolling
#   - Falls back to plain text gracefully
# =============================================================================

from textual.widgets import Static
from textual.containers import ScrollableContainer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawk_tui.core import Message


class MessagePreview(ScrollableContainer):
    """
    A widget for displaying rendered email content.

    Uses HTMLContent to convert HTML emails to native Textual widgets,
    providing real scrolling and clickable links.

    Usage:
        >>> preview = MessagePreview()
        >>> await preview.show_message(message)
    """

    DEFAULT_CSS = """
    MessagePreview {
        padding: 0 1;
    }

    MessagePreview > #preview-header {
        height: auto;
        margin-bottom: 1;
    }

    MessagePreview > #preview-body {
        height: auto;
    }

    MessagePreview > #preview-attachments {
        height: auto;
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        """
        Initialize the message preview.

        Args:
            **kwargs: Additional arguments passed to ScrollableContainer.
        """
        super().__init__(**kwargs)
        self._current_message: "Message | None" = None
        self._html_content = None  # Lazy-initialized HTMLContent widget

    def compose(self):
        """Compose the widget."""
        yield Static("Select a message to preview", id="preview-header")

    def _get_html_content(self):
        """Get or create the HTMLContent widget."""
        if self._html_content is None:
            from hawk_tui.ui.widgets.html_content import HTMLContent
            self._html_content = HTMLContent(id="preview-body")
        return self._html_content

    async def show_message(self, message: "Message") -> None:
        """
        Display a message in the preview.

        Args:
            message: Message to display.
        """
        self._current_message = message

        # Helper to escape Rich markup in user content
        def escape(text: str) -> str:
            if not text:
                return ""
            return text.replace("[", "\\[").replace("]", "\\]")

        # Build header display (escape user content to prevent markup injection)
        header_lines = [
            f"[bold]From:[/] {escape(message.display_sender)} <{escape(message.sender)}>",
            f"[bold]To:[/] {escape(', '.join(message.recipients))}",
        ]
        if message.cc:
            header_lines.append(f"[bold]CC:[/] {escape(', '.join(message.cc))}")
        header_lines.extend([
            f"[bold]Subject:[/] {escape(message.subject)}",
            f"[bold]Date:[/] {message.date_sent}",
            "─" * 50,
        ])
        header = "\n".join(header_lines)

        # Update header
        header_widget = self.query_one("#preview-header", Static)
        header_widget.update(header)

        # Remove any existing body/attachments widgets (must await removal!)
        for widget_id in ["preview-body", "preview-attachments"]:
            try:
                existing = self.query_one(f"#{widget_id}")
                await existing.remove()
            except Exception:
                pass

        # Render body - prefer HTML with native widgets
        if message.body_html:
            try:
                from hawk_tui.ui.widgets.html_content import HTMLContent
                html_widget = HTMLContent(id="preview-body")
                await self.mount(html_widget)
                html_widget.render_html(message.body_html)
            except Exception as e:
                # Fall back to plain text on error
                body_text = message.body_text if message.body_text else f"Rendering error: {e}"
                body_text = body_text.replace("[", "\\[")
                body_widget = Static(body_text, id="preview-body")
                await self.mount(body_widget)
        elif message.body_text:
            body_text = message.body_text.replace("[", "\\[")
            body_widget = Static(body_text, id="preview-body")
            await self.mount(body_widget)
        else:
            body_widget = Static("[dim]No content[/]", id="preview-body")
            await self.mount(body_widget)

        # Attachment summary
        if message.attachments:
            att_list = [f"📎 {escape(a.filename)} ({a.human_size})" for a in message.regular_attachments]
            if att_list:
                attachments_text = "─" * 50 + "\n" + "\n".join(att_list)
                att_widget = Static(attachments_text, id="preview-attachments")
                await self.mount(att_widget)

        # Scroll to top
        self.scroll_home()

    async def clear(self) -> None:
        """Clear the preview."""
        self._current_message = None

        # Reset header
        try:
            header_widget = self.query_one("#preview-header", Static)
            header_widget.update("Select a message to preview")
        except Exception:
            pass

        # Remove body and attachments (must await removal!)
        for widget_id in ["preview-body", "preview-attachments"]:
            try:
                existing = self.query_one(f"#{widget_id}")
                await existing.remove()
            except Exception:
                pass

    @property
    def current_message(self) -> "Message | None":
        """Get the currently displayed message."""
        return self._current_message
