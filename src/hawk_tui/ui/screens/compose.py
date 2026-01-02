# =============================================================================
# Compose Screen
# =============================================================================
# Screen for writing new emails, replies, and forwards.
#
# Features:
#   - To/CC/BCC fields with address completion
#   - Subject line
#   - Text editor for body
#   - Attachment management
#   - Send and save as draft
# =============================================================================

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, TextArea, Static, Button
from textual.containers import Vertical, Horizontal
from textual import work

from hawk_tui.core import Account
from hawk_tui.smtp import SMTPClient, EmailDraft, SendError


class ComposeScreen(Screen):
    """
    Screen for composing new emails.

    This screen provides a full editor for writing emails, with fields
    for recipients, subject, and body.

    Keybindings:
        - Ctrl+Enter: Send
        - Ctrl+S: Save as draft
        - Escape: Cancel (with confirmation if modified)
        - Ctrl+A: Add attachment
    """

    BINDINGS = [
        Binding("ctrl+s", "save_draft", "Save Draft"),
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+a", "add_attachment", "Attach", priority=True),
    ]

    CSS = """
    #compose-container {
        padding: 1;
    }

    #compose-headers {
        height: auto;
        margin-bottom: 1;
    }

    .compose-field {
        height: 3;
        margin-bottom: 0;
    }

    .field-label {
        width: 10;
        padding: 1 1 0 0;
        text-align: right;
    }

    .compose-field Input {
        width: 1fr;
    }

    #body-editor {
        height: 1fr;
        min-height: 10;
        border: tall $primary;
    }

    #attachments-display {
        height: auto;
        margin-top: 1;
        color: $text-muted;
    }

    #compose-actions {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    #compose-actions Button {
        margin: 0 1;
    }

    #status-display {
        height: 1;
        margin-top: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    def __init__(
        self,
        account: Account,
        *,
        draft: EmailDraft | None = None,
    ) -> None:
        """
        Initialize the compose screen.

        Args:
            account: Account to send from.
            draft: Optional pre-filled draft (for reply/forward).
        """
        super().__init__()
        self._account = account
        self._draft = draft or EmailDraft()
        self._sending = False

    def compose(self) -> ComposeResult:
        """
        Compose the compose screen layout.

        Layout:
        ┌─────────────────────────────────────────────────┐
        │                    Header                        │
        ├─────────────────────────────────────────────────┤
        │ To:      [                                    ] │
        │ CC:      [                                    ] │
        │ Subject: [                                    ] │
        ├─────────────────────────────────────────────────┤
        │                                                  │
        │              [Text Editor Area]                  │
        │                                                  │
        ├─────────────────────────────────────────────────┤
        │ Attachments: file1.pdf, file2.jpg               │
        ├─────────────────────────────────────────────────┤
        │ [Send]  [Save Draft]  [Cancel]                  │
        └─────────────────────────────────────────────────┘
        """
        yield Header()

        with Vertical(id="compose-container"):
            # Header fields
            with Vertical(id="compose-headers"):
                with Horizontal(classes="compose-field"):
                    yield Static("To:", classes="field-label")
                    yield Input(
                        value=", ".join(self._draft.to),
                        id="to-input",
                        placeholder="recipient@example.com"
                    )

                with Horizontal(classes="compose-field"):
                    yield Static("CC:", classes="field-label")
                    yield Input(
                        value=", ".join(self._draft.cc),
                        id="cc-input",
                        placeholder="cc@example.com"
                    )

                with Horizontal(classes="compose-field"):
                    yield Static("Subject:", classes="field-label")
                    yield Input(
                        value=self._draft.subject,
                        id="subject-input",
                        placeholder="Subject"
                    )

            # Body editor
            yield TextArea(self._draft.body_text, id="body-editor")

            # Attachments
            att_text = self._get_attachments_display()
            yield Static(att_text, id="attachments-display")

            # Status
            yield Static("", id="status-display")

            # Action buttons
            with Horizontal(id="compose-actions"):
                yield Button("Send", id="send-btn", variant="primary")
                yield Button("Save Draft", id="draft-btn")
                yield Button("Cancel", id="cancel-btn", variant="error")

        yield Footer()

    def _get_attachments_display(self) -> str:
        """Get the attachments display text."""
        if self._draft.attachments:
            names = [att[0] for att in self._draft.attachments]
            return f"Attachments: {', '.join(names)}"
        return "Attachments: None"

    def _update_status(self, text: str) -> None:
        """Update the status display."""
        try:
            status = self.query_one("#status-display", Static)
            status.update(text)
        except Exception:
            pass

    def _get_current_draft(self) -> EmailDraft:
        """Build draft from current form values."""
        to_input = self.query_one("#to-input", Input)
        cc_input = self.query_one("#cc-input", Input)
        subject_input = self.query_one("#subject-input", Input)
        body_editor = self.query_one("#body-editor", TextArea)

        # Parse comma-separated addresses
        to_list = [addr.strip() for addr in to_input.value.split(",") if addr.strip()]
        cc_list = [addr.strip() for addr in cc_input.value.split(",") if addr.strip()]

        return EmailDraft(
            to=to_list,
            cc=cc_list,
            bcc=self._draft.bcc,  # Keep original BCC
            subject=subject_input.value,
            body_text=body_editor.text,
            body_html="",  # Plain text only for now
            attachments=self._draft.attachments,
            in_reply_to=self._draft.in_reply_to,
            references=self._draft.references,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "send-btn":
            self.action_send()
        elif event.button.id == "draft-btn":
            self.action_save_draft()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def action_send(self) -> None:
        """Send the email."""
        if self._sending:
            return

        # Validate
        draft = self._get_current_draft()
        if not draft.to:
            self.notify("Please enter at least one recipient", severity="error")
            return
        if not draft.subject:
            self.notify("Please enter a subject", severity="warning")
            # Allow sending without subject

        # Start send in background
        self._do_send(draft)

    @work(exclusive=True)
    async def _do_send(self, draft: EmailDraft) -> None:
        """Background worker to send email."""
        self._sending = True
        self._update_status("Connecting to SMTP server...")

        # Disable send button while sending
        try:
            send_btn = self.query_one("#send-btn", Button)
            send_btn.disabled = True
        except Exception:
            pass

        try:
            # Connect to SMTP
            smtp = SMTPClient(self._account)
            await smtp.connect()

            self._update_status("Sending...")

            # Send the email
            message_id = await smtp.send(draft)

            # Disconnect
            await smtp.disconnect()

            self._update_status("Sent!")
            self.notify(f"Email sent to {', '.join(draft.to)}", timeout=3)

            # Return to previous screen after a brief pause
            self.app.pop_screen()

        except SendError as e:
            self._update_status(f"Send failed: {e}")
            self.notify(f"Failed to send: {e}", severity="error")
        except Exception as e:
            self._update_status(f"Error: {e}")
            self.notify(f"Error: {e}", severity="error")
        finally:
            self._sending = False
            try:
                send_btn = self.query_one("#send-btn", Button)
                send_btn.disabled = False
            except Exception:
                pass

    def action_save_draft(self) -> None:
        """Save as draft."""
        # TODO: Save to drafts folder via IMAP APPEND
        self.notify("Draft saving not yet implemented")

    def action_cancel(self) -> None:
        """Cancel and return to previous screen."""
        # TODO: Confirm if modified
        self.app.pop_screen()

    def action_add_attachment(self) -> None:
        """Prompt for file path and add as attachment."""
        from hawk_tui.ui.screens.file_picker import FilePickerScreen

        def handle_file_selected(path: str | None) -> None:
            if path:
                self._add_attachment_from_path(path)

        self.app.push_screen(FilePickerScreen(), handle_file_selected)

    def _add_attachment_from_path(self, path: str) -> None:
        """Add an attachment from a file path."""
        import os
        import mimetypes
        from pathlib import Path

        # Expand ~ and environment variables
        expanded_path = os.path.expanduser(os.path.expandvars(path))
        file_path = Path(expanded_path)

        if not file_path.exists():
            self.notify(f"File not found: {path}", severity="error")
            return

        if not file_path.is_file():
            self.notify(f"Not a file: {path}", severity="error")
            return

        # Check file size (limit to 25MB)
        max_size = 25 * 1024 * 1024
        if file_path.stat().st_size > max_size:
            self.notify("File too large (max 25MB)", severity="error")
            return

        try:
            # Read file data
            data = file_path.read_bytes()

            # Guess content type
            content_type, _ = mimetypes.guess_type(str(file_path))
            if not content_type:
                content_type = "application/octet-stream"

            # Add to attachments
            filename = file_path.name
            self._draft.attachments.append((filename, content_type, data))

            # Update display
            att_display = self.query_one("#attachments-display", Static)
            att_display.update(self._get_attachments_display())

            self.notify(f"Attached: {filename}")

        except Exception as e:
            self.notify(f"Error reading file: {e}", severity="error")
