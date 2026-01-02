# =============================================================================
# Message List Widget
# =============================================================================
# A table/list view of email messages.
#
# Features:
#   - Columns: Read status, Star, From, Subject, Date
#   - Sortable by any column
#   - Keyboard navigation
#   - Selection (single and multi-select)
#   - Virtual scrolling for large mailboxes
# =============================================================================

from textual.widgets import DataTable
from textual.widgets.data_table import RowKey
from textual.binding import Binding
from textual.message import Message as TextualMessage
from typing import TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from hawk_tui.core import Message


class MessageList(DataTable):
    """
    A table widget displaying email messages.

    Shows a list of messages with columns for read status, sender,
    subject, and date.

    Multi-select:
        - x or Space: Toggle selection of current row (sets anchor)
        - X (shift+x): Extend selection from anchor to current row
        - Ctrl+A: Select all / Deselect all
        - Escape: Clear selection

    Usage:
        >>> list = MessageList()
        >>> await list.load_messages(messages)
    """

    BINDINGS = [
        Binding("x", "toggle_select", "Select", show=False),
        Binding("X", "extend_select", "Extend Select", show=False),
        Binding("space", "toggle_select", "Select", show=False),
        Binding("ctrl+a", "select_all", "Select All", show=False, priority=True),
    ]

    # Column configuration
    COLUMNS = [
        ("☐", 2),       # Selection checkbox
        ("", 2),        # Read/unread indicator
        ("★", 2),       # Star/flag indicator
        ("⚠", 2),       # Junk/spam indicator
        ("From", 25),   # Sender
        ("Subject", 0), # Subject (flexible width)
        ("Date", 12),   # Date
    ]

    class SelectionChanged(TextualMessage):
        """Posted when selection changes."""
        def __init__(self, count: int) -> None:
            super().__init__()
            self.count = count

    def __init__(self, **kwargs) -> None:
        """
        Initialize the message list.

        Args:
            **kwargs: Additional arguments passed to DataTable.
        """
        super().__init__(**kwargs)
        self._messages: dict[RowKey, "Message"] = {}
        self._selected: set[RowKey] = set()  # Track selected rows
        self._selection_anchor: int | None = None  # Anchor point for shift-select

        # Configure table
        self.cursor_type = "row"
        self.zebra_stripes = True

    def on_mount(self) -> None:
        """Set up columns when widget is mounted."""
        for label, width in self.COLUMNS:
            if width > 0:
                self.add_column(label, width=width)
            else:
                self.add_column(label)  # Flexible width

    async def load_messages(self, messages: list["Message"]) -> None:
        """
        Load messages into the table.

        Args:
            messages: List of messages to display.
        """
        self.clear()
        self._messages.clear()
        self._selected.clear()  # Clear selection when loading new messages
        self._selection_anchor = None

        for message in messages:
            row_key = self._add_message_row(message)
            self._messages[row_key] = message

    def _add_message_row(self, message: "Message") -> RowKey:
        """
        Add a message as a table row.

        Returns:
            The RowKey for the added row.
        """
        # Selection checkbox (not selected by default)
        checkbox = "☐"

        # Read indicator
        read_indicator = " " if message.is_read else "●"

        # Star indicator
        star_indicator = "★" if message.is_flagged else " "

        # Junk/spam indicator
        junk_indicator = "[red]⚠[/]" if message.is_spam else " "

        # Sender (truncate if needed)
        sender = message.display_sender
        if len(sender) > 25:
            sender = sender[:22] + "..."

        # Subject
        subject = message.subject or "(no subject)"

        # Date formatting
        date_str = self._format_date(message.date_sent)

        # Style based on read status
        if not message.is_read:
            # Bold for unread
            sender = f"[bold]{sender}[/]"
            subject = f"[bold]{subject}[/]"

        return self.add_row(
            checkbox,
            read_indicator,
            star_indicator,
            junk_indicator,
            sender,
            subject,
            date_str,
        )

    def _format_date(self, dt: datetime | None) -> str:
        """
        Format a date for display in local time.

        Shows:
            - Time if today
            - Day name if this week
            - Date otherwise
        """
        if not dt:
            return ""

        now = datetime.now()

        # Convert to local time if timezone-aware (dates are stored in UTC)
        if dt.tzinfo is not None:
            try:
                # astimezone() with no arg converts to local timezone
                dt_local = dt.astimezone().replace(tzinfo=None)
            except Exception:
                dt_local = dt.replace(tzinfo=None)
        else:
            dt_local = dt

        # Compare dates
        if dt_local.date() == now.date():
            return dt_local.strftime("%H:%M")
        elif (now.date() - dt_local.date()).days < 7:
            return dt_local.strftime("%a")
        else:
            return dt_local.strftime("%b %d")

    def get_selected_message(self) -> "Message | None":
        """
        Get the currently selected message.

        Returns:
            Selected Message or None.
        """
        row_key = self.cursor_row
        if row_key is not None:
            # Get actual RowKey object
            # Note: cursor_row returns index, we need to get the key
            try:
                row_key_obj = list(self._messages.keys())[row_key]
                return self._messages.get(row_key_obj)
            except (IndexError, KeyError):
                pass
        return None

    def get_selected_messages(self) -> list["Message"]:
        """
        Get all selected messages (for multi-select operations).

        If no messages are explicitly selected, returns the current cursor row.

        Returns:
            List of selected messages.
        """
        if self._selected:
            # Return all selected messages
            return [self._messages[rk] for rk in self._selected if rk in self._messages]
        else:
            # Fall back to cursor row if nothing explicitly selected
            msg = self.get_selected_message()
            return [msg] if msg else []

    @property
    def selection_count(self) -> int:
        """Return number of selected messages."""
        return len(self._selected)

    def action_toggle_select(self) -> None:
        """Toggle selection of the current row and set as anchor."""
        row_idx = self.cursor_row
        if row_idx is None:
            return

        row_key = self._get_current_row_key()
        if row_key is None:
            return

        # Set anchor for shift-select
        self._selection_anchor = row_idx

        if row_key in self._selected:
            self._selected.discard(row_key)
            self._update_checkbox(row_key, selected=False)
        else:
            self._selected.add(row_key)
            self._update_checkbox(row_key, selected=True)

        self.post_message(self.SelectionChanged(len(self._selected)))

    def action_extend_select(self) -> None:
        """Extend selection from anchor to current row (shift+space)."""
        row_idx = self.cursor_row
        if row_idx is None:
            return

        # If no anchor, just do regular toggle
        if self._selection_anchor is None:
            self.action_toggle_select()
            return

        # Get range between anchor and current
        start = min(self._selection_anchor, row_idx)
        end = max(self._selection_anchor, row_idx)

        # Get all row keys
        row_keys = list(self._messages.keys())

        # Select all rows in range
        for i in range(start, end + 1):
            if i < len(row_keys):
                row_key = row_keys[i]
                if row_key not in self._selected:
                    self._selected.add(row_key)
                    self._update_checkbox(row_key, selected=True)

        self.post_message(self.SelectionChanged(len(self._selected)))

    def action_select_all(self) -> None:
        """Select all messages."""
        if len(self._selected) == len(self._messages):
            # All selected - deselect all
            self.clear_selection()
        else:
            # Select all
            for row_key in self._messages.keys():
                self._selected.add(row_key)
                self._update_checkbox(row_key, selected=True)
            self.post_message(self.SelectionChanged(len(self._selected)))

    def clear_selection(self) -> None:
        """Clear all selections."""
        for row_key in list(self._selected):
            self._update_checkbox(row_key, selected=False)
        self._selected.clear()
        self._selection_anchor = None
        self.post_message(self.SelectionChanged(0))

    def _get_current_row_key(self) -> RowKey | None:
        """Get the RowKey for the current cursor row."""
        row_idx = self.cursor_row
        if row_idx is not None:
            try:
                return list(self._messages.keys())[row_idx]
            except IndexError:
                pass
        return None

    def _update_checkbox(self, row_key: RowKey, selected: bool) -> None:
        """Update the checkbox display for a row."""
        columns = list(self.columns.keys())
        if columns:
            checkbox = "[green]☑[/]" if selected else "☐"
            self.update_cell(row_key, columns[0], checkbox)

    def refresh_message(self, message: "Message") -> None:
        """
        Refresh the display of a single message.

        Use after changing flags (read, starred, etc.)

        Args:
            message: Message to refresh.
        """
        # Find row key for this message
        for row_key, msg in self._messages.items():
            if msg.id == message.id:
                # Update the stored message
                self._messages[row_key] = message

                # Update the row display
                # Get column keys (checkbox is column 0, so indicators start at 1)
                columns = list(self.columns.keys())
                if len(columns) >= 7:
                    # Checkbox (column 0) - preserve current selection state
                    is_selected = row_key in self._selected
                    checkbox = "[green]☑[/]" if is_selected else "☐"
                    self.update_cell(row_key, columns[0], checkbox)

                    # Read indicator (column 1)
                    read_indicator = " " if message.is_read else "●"
                    self.update_cell(row_key, columns[1], read_indicator)

                    # Star indicator (column 2)
                    star_indicator = "★" if message.is_flagged else " "
                    self.update_cell(row_key, columns[2], star_indicator)

                    # Junk indicator (column 3)
                    junk_indicator = "[red]⚠[/]" if message.is_spam else " "
                    self.update_cell(row_key, columns[3], junk_indicator)

                    # Sender (column 4)
                    sender = message.display_sender
                    if len(sender) > 25:
                        sender = sender[:22] + "..."
                    if not message.is_read:
                        sender = f"[bold]{sender}[/]"
                    self.update_cell(row_key, columns[4], sender)

                    # Subject (column 5)
                    subject = message.subject or "(no subject)"
                    if not message.is_read:
                        subject = f"[bold]{subject}[/]"
                    self.update_cell(row_key, columns[5], subject)

                break

    def remove_message(self, message: "Message") -> bool:
        """
        Remove a message from the list.

        Args:
            message: Message to remove.

        Returns:
            True if message was removed, False if not found.
        """
        # Find and remove the row
        for row_key, msg in list(self._messages.items()):
            if msg.id == message.id:
                self.remove_row(row_key)
                del self._messages[row_key]
                self._selected.discard(row_key)  # Also remove from selection
                return True
        return False
