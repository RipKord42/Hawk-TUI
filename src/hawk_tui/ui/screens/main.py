# =============================================================================
# Main Screen
# =============================================================================
# The primary view of Hawk-TUI, showing:
#   - Left panel: Folder tree (collapsible)
#   - Center panel: Message list
#   - Bottom/Right panel: Message preview
#
# Layout adapts to terminal size:
#   - Wide terminals: 3-column layout
#   - Narrow terminals: 2-column with toggle-able preview
# =============================================================================

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from textual.containers import Horizontal, Vertical
from textual import work

from hawk_tui.ui.widgets.folder_tree import FolderTree
from hawk_tui.ui.widgets.message_list import MessageList
from hawk_tui.ui.widgets.message_preview import MessagePreview
from hawk_tui.core import Account, Folder, Message
from hawk_tui.storage.database import Database
from hawk_tui.storage.repository import Repository
from hawk_tui.imap.client import IMAPClient, IMAPAuthenticationError
from hawk_tui.imap.sync import SyncManager, SyncStatus
from hawk_tui.imap.idle import IdleWorker, IdleEvent
from hawk_tui.config import Config
from hawk_tui.ui.screens.password import PasswordScreen
from hawk_tui.ui.screens.compose import ComposeScreen
from hawk_tui.ui.screens.search import SearchScreen
from hawk_tui.smtp import SMTPClient, EmailDraft
from hawk_tui.spam import SpamClassifier
from hawk_tui.core import FolderType


class MainScreen(Screen):
    """
    The main email viewing screen.

    This is the default screen shown when Hawk-TUI starts. It provides
    the classic 3-pane email client layout:
        - Folder tree on the left
        - Message list in the center
        - Message preview on the right or bottom

    Keybindings:
        - j/k or arrows: Navigate message list
        - Enter: Open message in preview
        - r: Reply
        - R: Reply All
        - f: Forward
        - d: Delete
        - J: Mark as Junk
        - s: Toggle star/flag
        - v: View HTML in browser
        - I: Render as image (Playwright + Kitty)
    """

    # Screen-specific bindings (in addition to app-level bindings)
    BINDINGS = [
        Binding("j", "cursor_down", "Next", show=False),
        Binding("k", "cursor_up", "Previous", show=False),
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
        Binding("enter", "select_message", "View", show=True),
        Binding("r", "reply", "Reply"),
        Binding("R", "reply_all", "Reply All"),
        Binding("f", "forward", "Forward", show=False),
        Binding("d", "delete", "Delete"),
        Binding("delete", "delete", "Delete", show=False),
        Binding("J", "mark_junk", "Junk", show=False),
        Binding("!", "mark_not_junk", "Not Junk", show=False),
        Binding("*", "toggle_star", "Star"),
        Binding("u", "mark_unread", "Unread", show=False),
        Binding("ctrl+r", "sync", "Sync"),
        Binding("v", "view_html", "View HTML"),
        Binding("I", "view_image", "Render", show=True),
        Binding("tab", "focus_next_pane", "Next Pane", show=False),
        Binding("shift+tab", "focus_prev_pane", "Prev Pane", show=False),
        Binding("E", "empty_folder", "Empty", show=False),
        Binding("a", "save_attachments", "Attachments", show=False),
        Binding("/", "search", "Search"),
        Binding("escape", "clear_search", "Clear", show=False),
    ]

    # CSS for this screen
    CSS = """
    #main-container {
        height: 1fr;
    }

    #sidebar {
        width: 28;
        min-width: 20;
        max-width: 40;
        background: $surface-darken-1;
        border-right: solid $primary;
    }

    #sidebar-header {
        background: $primary;
        color: $text;
        text-align: center;
        height: 3;
        padding: 1;
    }

    #folder-tree {
        height: 1fr;
    }

    #content {
        width: 1fr;
    }

    #message-list {
        height: 50%;
        border-bottom: solid $primary;
    }

    #message-preview {
        height: 50%;
    }

    #status-line {
        height: 1;
        background: $surface-darken-2;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        """Initialize the main screen."""
        super().__init__()
        self._db: Database | None = None
        self._repo: Repository | None = None
        self._current_folder: Folder | None = None
        self._current_account: Account | None = None
        self._syncing = False

        # Search state
        self._search_active = False
        self._search_query = ""

        # Initialize spam classifier for training
        self._spam_classifier = SpamClassifier()
        self._spam_classifier.load()
        self._spam_config = self._load_spam_config()

        # IDLE worker for push notifications
        self._idle_worker: IdleWorker | None = None
        self._idle_enabled = self._load_idle_config()

    def _load_spam_config(self) -> dict:
        """Load spam configuration settings."""
        try:
            config = Config.load()
            return {
                "enabled": config.spam.enabled,
                "threshold": config.spam.threshold,
                "auto_move_to_junk": config.spam.auto_move_to_junk,
                "train_on_move": config.spam.train_on_move,
            }
        except Exception:
            return {
                "enabled": True,
                "threshold": 0.7,
                "auto_move_to_junk": True,
                "train_on_move": True,
            }

    def _load_idle_config(self) -> bool:
        """Load IDLE/push notification configuration."""
        try:
            config = Config.load()
            return config.sync.use_idle
        except Exception:
            return True  # Default to enabled

    def compose(self) -> ComposeResult:
        """
        Compose the main screen layout.

        The layout is:
        +--------------------------------------------------+
        |                    Header                         |
        +----------+---------------------------------------+
        |  Folder  |          Message List                  |
        |   Tree   |----------------------------------------|
        |          |          Message Preview               |
        +----------+---------------------------------------+
        | Status                                            |
        +--------------------------------------------------+
        |                    Footer                         |
        +--------------------------------------------------+
        """
        yield Header()

        with Horizontal(id="main-container"):
            # Left sidebar - folder tree
            with Vertical(id="sidebar"):
                yield Static("Mailboxes", id="sidebar-header")
                yield FolderTree("", id="folder-tree")

            # Main content area
            with Vertical(id="content"):
                # Message list
                yield MessageList(id="message-list")
                # Message preview (not focusable - Tab skips it)
                yield MessagePreview(id="message-preview", can_focus=False)

        yield Static("Ready", id="status-line")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize database connection and load data."""
        self.update_status("Connecting to database...")

        # Connect to database
        self._db = Database()
        await self._db.connect()
        self._repo = Repository(self._db)

        # Sync accounts from config to database
        self.update_status("Syncing accounts...")
        await self._sync_config_accounts()

        # Load data
        self.update_status("Loading folders...")
        await self._load_folders()

        # Focus the folder tree initially
        self.query_one("#folder-tree", FolderTree).focus()

        # Start IDLE push notifications if enabled
        if self._idle_enabled:
            self._start_idle()  # @work decorator runs it in background
            self.update_status("Ready - Starting IDLE push... (Ctrl+R to sync)")
        else:
            self.update_status("Ready - Press Ctrl+R to sync")

    async def _sync_config_accounts(self) -> None:
        """Sync accounts from config file to database."""
        try:
            config = Config.load()
            for name, cfg_account in config.accounts.items():
                if not cfg_account.enabled:
                    continue
                # Check if account already exists in database
                existing = await self._repo.get_account_by_name(name)
                if existing is None:
                    # Create new account in database
                    account = Account(
                        name=name,
                        email=cfg_account.email,
                        display_name=cfg_account.display_name,
                        imap_host=cfg_account.imap_host,
                        imap_port=cfg_account.imap_port,
                        smtp_host=cfg_account.smtp_host,
                        smtp_port=cfg_account.smtp_port,
                    )
                    await self._repo.save_account(account)
                    self.notify(f"Added account: {name}")
                else:
                    # Update existing account with current config values
                    existing.email = cfg_account.email
                    existing.display_name = cfg_account.display_name
                    existing.imap_host = cfg_account.imap_host
                    existing.imap_port = cfg_account.imap_port
                    existing.imap_security = cfg_account.imap_security
                    existing.smtp_host = cfg_account.smtp_host
                    existing.smtp_port = cfg_account.smtp_port
                    existing.smtp_security = cfg_account.smtp_security
                    await self._repo.save_account(existing)
        except Exception as e:
            self.notify(f"Error syncing accounts: {e}", severity="error")

    async def on_unmount(self) -> None:
        """Clean up database connection and IDLE worker."""
        # Stop IDLE worker
        if self._idle_worker:
            await self._idle_worker.stop()
            self._idle_worker = None

        # Close database
        if self._db:
            await self._db.close()

    async def _load_folders(self) -> None:
        """Load folders from database into the tree."""
        if not self._repo:
            return

        # Get all accounts and their folders
        accounts = await self._repo.get_all_accounts()

        if not accounts:
            self.notify(
                "No accounts configured. Press Ctrl+S for settings.",
                severity="warning",
                timeout=10,
            )
            return

        folders_by_account: dict[int, list[Folder]] = {}
        for account in accounts:
            if account.id:
                folders = await self._repo.get_folders(account.id)
                folders_by_account[account.id] = folders
                # Set the first account as current
                if self._current_account is None:
                    self._current_account = account

        # Load into tree
        tree = self.query_one("#folder-tree", FolderTree)
        await tree.load_accounts(accounts, folders_by_account)

        # Auto-select INBOX if available
        if self._current_account and self._current_account.id:
            inbox = await self._repo.get_folder_by_name(
                self._current_account.id, "INBOX"
            )
            if inbox:
                await self._select_folder(inbox)

    async def _select_folder(self, folder: Folder) -> None:
        """
        Select a folder and load its messages.

        Args:
            folder: Folder to select.
        """
        self._current_folder = folder

        # Update current account to match the folder's account
        if self._repo and folder.account_id:
            account = await self._repo.get_account(folder.account_id)
            if account:
                self._current_account = account

        self.update_status(f"Loading {folder.name}...")

        # Clear preview
        preview = self.query_one("#message-preview", MessagePreview)
        await preview.clear()

        # Load messages (limit=5000 for now; proper pagination in 0.2.0)
        if self._repo and folder.id:
            messages = await self._repo.get_messages(folder.id, limit=5000)
            message_list = self.query_one("#message-list", MessageList)
            await message_list.load_messages(messages)

            count = len(messages)
            unread = sum(1 for m in messages if not m.is_read)
            self.update_status(f"{folder.name}: {count} messages ({unread} unread)")
        else:
            self.update_status(f"{folder.name}: No messages")

    def update_status(self, text: str) -> None:
        """Update the status line."""
        status = self.query_one("#status-line", Static)
        status.update(text)

    # -------------------------------------------------------------------------
    # Sync Operations
    # -------------------------------------------------------------------------

    @work(exclusive=True)
    async def _do_sync(self) -> None:
        """Background worker to perform sync for ALL accounts."""
        if self._syncing or not self._repo:
            return

        self._syncing = True

        # Get all accounts
        accounts = await self._repo.get_all_accounts()
        if not accounts:
            self.notify("No accounts configured", severity="warning")
            self._syncing = False
            return

        # Track totals across all accounts
        total_new = 0
        total_updated = 0
        total_spam = 0
        errors = []
        accounts_needing_password = []

        try:
            self.notify(f"Syncing {len(accounts)} accounts...", timeout=2)

            for account in accounts:
                self.update_status(f"Syncing {account.name}...")
                self.notify(f"Starting sync: {account.name}", timeout=2)

                try:
                    # Create IMAP client and sync manager for this account
                    client = IMAPClient(account)
                    sync = SyncManager(client, self._repo, account)

                    # Progress callback
                    def on_progress(progress, acct_name=account.name):
                        if progress.folder:
                            self.update_status(f"[{acct_name}] {progress.folder}...")

                    # Run sync for this account
                    result = await sync.sync_all(progress_callback=on_progress)

                    # Disconnect
                    await client.disconnect()

                    # Accumulate results
                    total_new += result.new_messages
                    total_updated += result.updated_messages
                    total_spam += result.spam_moved

                    if not result.success:
                        errors.extend(result.errors)

                except IMAPAuthenticationError as e:
                    # Any auth error should prompt for password re-entry
                    accounts_needing_password.append(account)
                except Exception as e:
                    errors.append(f"{account.name}: {e}")

            # Show summary
            if total_new > 0 or total_updated > 0 or total_spam > 0:
                msg = f"Synced: {total_new} new"
                if total_updated:
                    msg += f", {total_updated} updated"
                if total_spam:
                    msg += f", {total_spam} spam"
                self.update_status(msg)
                self.notify(msg, timeout=3)
            else:
                self.update_status("Sync complete - no changes")

            # Reload current folder
            await self._reload_folders_and_messages()

            # Handle password prompts (only prompt for first one)
            if accounts_needing_password:
                self._current_account = accounts_needing_password[0]
                self.update_status(f"Password required for {self._current_account.name}...")
                self.call_later(self._prompt_for_password)

            # Report errors
            if errors:
                for err in errors[:3]:  # Show first 3 errors
                    self.notify(f"Sync error: {err}", severity="error")

        except Exception as e:
            self.update_status(f"Sync error: {e}")
            self.notify(f"Sync error: {e}", severity="error")
        finally:
            self._syncing = False

    def _prompt_for_password(self) -> None:
        """Show password prompt dialog."""
        if not self._current_account:
            return

        def on_password_entered(password: str | None) -> None:
            """Callback when password is entered."""
            if password and self._current_account:
                # Save password to keyring
                import keyring
                keyring.set_password(
                    self._current_account.keyring_service,
                    self._current_account.email,
                    password,
                )
                self.notify("Password saved to keyring")
                # Retry sync
                self._do_sync()
            else:
                self.update_status("Sync cancelled - no password provided")

        # Push the password screen
        self.app.push_screen(
            PasswordScreen(
                account_name=self._current_account.name,
                email=self._current_account.email,
            ),
            on_password_entered,
        )

    async def _reload_folders_and_messages(self) -> None:
        """Reload folders and current message list after sync."""
        # Reload folder tree
        await self._load_folders()

        # Reload current folder's messages
        if self._current_folder:
            await self._select_folder(self._current_folder)

    # -------------------------------------------------------------------------
    # IDLE / Push Notifications
    # -------------------------------------------------------------------------

    @work(exclusive=False, name="idle-worker")
    async def _start_idle(self) -> None:
        """Start IDLE push notifications for all accounts."""
        if not self._idle_enabled:
            return

        if not self._repo:
            return

        # Get all accounts
        accounts = await self._repo.get_all_accounts()
        if not accounts:
            return

        try:
            # Create and start IDLE worker
            self._idle_worker = IdleWorker()
            self._idle_worker.on_event = self._handle_idle_event
            await self._idle_worker.start(accounts)

            self.update_status("IDLE push enabled - watching for new mail")
            self.notify("IDLE push enabled", timeout=3)
        except Exception as e:
            # IDLE failed to start - not critical, just log it
            self.update_status(f"IDLE unavailable: {e}")

    async def _handle_idle_event(self, event: IdleEvent) -> None:
        """
        Handle an IDLE event (new mail, expunge, etc.).

        This is called by the IdleWorker when changes are detected.
        """
        if event.event_type == "new_mail":
            # New mail detected - run incremental sync
            self.notify(
                f"New mail in {event.account_name}",
                title="New Mail",
                timeout=5,
            )
            # Trigger a sync for this account
            self._do_idle_sync(event.account_id)

        elif event.event_type == "expunge":
            # Message deleted - refresh if viewing that folder
            self._do_idle_sync(event.account_id)

        elif event.event_type == "flags":
            # Flag change - might need to refresh display
            if self._current_account and self._current_account.id == event.account_id:
                if self._current_folder and self._current_folder.name == event.folder_name:
                    await self._reload_folders_and_messages()

    @work(exclusive=False, name="idle-sync")
    async def _do_idle_sync(self, account_id: int) -> None:
        """
        Perform an incremental sync triggered by IDLE.

        This runs in the background and doesn't block the UI.
        """
        if not self._repo or self._syncing:
            return

        # Find the account
        account = await self._repo.get_account(account_id)
        if not account:
            return

        try:
            # Create client and sync manager
            client = IMAPClient(account)
            sync = SyncManager(client, self._repo, account)

            # Do incremental sync (just INBOX for speed)
            await client.connect()

            # Sync just INBOX for now
            inbox = await self._repo.get_folder_by_name(account_id, "INBOX")
            if inbox:
                await sync.sync_folder(inbox)

            await client.disconnect()

            # Reload folders (for unread counts) and messages if viewing this account
            if self._current_account and self._current_account.id == account_id:
                await self._reload_folders_and_messages()
            else:
                # At least refresh folder tree for unread counts
                await self._load_folders()

        except Exception as e:
            # Log error but don't show to user - IDLE will retry
            self.update_status(f"IDLE sync error: {e}")

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    async def on_tree_node_selected(self, event: FolderTree.NodeSelected) -> None:
        """Handle folder selection in the tree."""
        node = event.node
        if node.data and node.data.get("type") == "folder":
            folder_id = node.data.get("id")
            if folder_id and self._repo:
                folder = await self._repo.get_folder(folder_id)
                if folder:
                    await self._select_folder(folder)

    async def on_data_table_row_selected(
        self, event: MessageList.RowSelected
    ) -> None:
        """Handle message selection (Enter key) in the list - marks as read."""
        message_list = self.query_one("#message-list", MessageList)
        message = message_list.get_selected_message()

        if message and message.id and self._repo:
            # Fetch full message with body content
            full_message = await self._repo.get_message(message.id)
            if full_message:
                preview = self.query_one("#message-preview", MessagePreview)
                await preview.show_message(full_message)

                # Mark as read when explicitly selected
                if not full_message.is_read:
                    full_message.mark_read()
                    await self._repo.update_message_flags(message.id, full_message.flags)
                    message_list.refresh_message(full_message)

    async def on_data_table_row_highlighted(
        self, event: MessageList.RowHighlighted
    ) -> None:
        """Handle cursor movement - auto-preview without marking as read."""
        message_list = self.query_one("#message-list", MessageList)
        message = message_list.get_selected_message()

        if message and message.id and self._repo:
            # Fetch full message with body content
            full_message = await self._repo.get_message(message.id)
            if full_message:
                preview = self.query_one("#message-preview", MessagePreview)
                await preview.show_message(full_message)
                # Note: Don't mark as read on highlight - only on explicit selection

    # -------------------------------------------------------------------------
    # Action Handlers
    # -------------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        """Move to next message."""
        message_list = self.query_one("#message-list", MessageList)
        message_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move to previous message."""
        message_list = self.query_one("#message-list", MessageList)
        message_list.action_cursor_up()

    async def action_select_message(self) -> None:
        """Select and preview the current message."""
        message_list = self.query_one("#message-list", MessageList)
        message = message_list.get_selected_message()

        if message and message.id and self._repo:
            # Fetch full message with body content
            full_message = await self._repo.get_message(message.id)
            if full_message:
                preview = self.query_one("#message-preview", MessagePreview)
                await preview.show_message(full_message)

                # Mark as read
                if not full_message.is_read:
                    full_message.mark_read()
                    await self._repo.update_message_flags(message.id, full_message.flags)
                    message_list.refresh_message(full_message)

    def action_sync(self) -> None:
        """Trigger a sync operation."""
        if self._syncing:
            self.notify("Sync already in progress...")
            return
        self._do_sync()

    def action_compose(self) -> None:
        """Open compose screen for new email."""
        if not self._current_account:
            self.notify("No account selected", severity="warning")
            return

        self.app.push_screen(ComposeScreen(self._current_account))

    async def action_reply(self) -> None:
        """Reply to selected message."""
        await self._open_compose_for_message(reply_all=False)

    async def action_reply_all(self) -> None:
        """Reply all to selected message."""
        await self._open_compose_for_message(reply_all=True)

    async def action_forward(self) -> None:
        """Forward selected message."""
        await self._open_compose_for_message(forward=True)

    async def _open_compose_for_message(
        self,
        *,
        reply_all: bool = False,
        forward: bool = False,
    ) -> None:
        """Open compose screen for reply/reply-all/forward."""
        if not self._current_account:
            self.notify("No account selected", severity="warning")
            return

        message_list = self.query_one("#message-list", MessageList)
        message = message_list.get_selected_message()

        if not message:
            self.notify("No message selected", severity="warning")
            return

        # Fetch full message with body
        if self._repo and message.id:
            full_message = await self._repo.get_message(message.id)
            if full_message:
                message = full_message

        # Create the draft using SMTP client helper methods
        smtp = SMTPClient(self._current_account)

        if forward:
            draft = smtp.create_forward(message)
        else:
            draft = smtp.create_reply(message, reply_all=reply_all)

        # Open compose screen with the draft
        self.app.push_screen(ComposeScreen(self._current_account, draft=draft))

    async def action_delete(self) -> None:
        """Delete selected message(s) (moves to Trash or permanently deletes)."""
        message_list = self.query_one("#message-list", MessageList)
        messages = message_list.get_selected_messages()

        if not messages:
            self.notify("No message selected", severity="warning")
            return

        if not self._current_account or not self._current_folder:
            self.notify("Cannot delete: missing context", severity="error")
            return

        # Filter messages with valid UIDs
        valid_messages = [m for m in messages if m.uid]
        if not valid_messages:
            self.notify("No valid messages to delete", severity="error")
            return

        uids = [m.uid for m in valid_messages]

        try:
            # Connect to IMAP
            client = IMAPClient(self._current_account)
            await client.connect()

            try:
                # Check if we're already in Trash
                is_in_trash = self._current_folder.folder_type == FolderType.TRASH

                if is_in_trash:
                    # Permanently delete from Trash
                    await client.delete_messages(self._current_folder.name, uids)
                    action_text = "Permanently deleted"
                else:
                    # Find Trash folder and move messages there
                    trash_folder = await self._repo.get_folder_by_type(
                        self._current_account.id,
                        FolderType.TRASH
                    )

                    if trash_folder:
                        await client.move_messages(
                            self._current_folder.name,
                            trash_folder.name,
                            uids
                        )
                        action_text = "Moved to Trash"
                    else:
                        # No Trash folder found, permanently delete
                        await client.delete_messages(self._current_folder.name, uids)
                        action_text = "Deleted"

                # Disconnect from IMAP
                await client.disconnect()

                # Delete from local database and remove from list view
                for message in valid_messages:
                    if self._repo and message.id:
                        await self._repo.delete_message(message.id)
                    message_list.remove_message(message)

                # Clear selection
                message_list.clear_selection()

                # Show the next selected message in preview (auto-preview after delete)
                preview = self.query_one("#message-preview", MessagePreview)
                next_message = message_list.get_selected_message()
                if next_message and next_message.id and self._repo:
                    full_next = await self._repo.get_message(next_message.id)
                    if full_next:
                        await preview.show_message(full_next)
                else:
                    # No next message, clear preview
                    await preview.clear()

                count = len(valid_messages)
                if count == 1:
                    subject = valid_messages[0].subject[:30] if valid_messages[0].subject else "(no subject)"
                    self.notify(f"{action_text}: {subject}")
                else:
                    self.notify(f"{action_text}: {count} messages")

                # Update folder counts
                if self._current_folder and self._repo:
                    # Count how many deleted messages were unread
                    unread_deleted = sum(1 for m in valid_messages if not m.is_read)
                    self._current_folder.total_messages = max(0, self._current_folder.total_messages - count)
                    self._current_folder.unread_count = max(0, self._current_folder.unread_count - unread_deleted)
                    await self._repo.save_folder(self._current_folder)

                    # Refresh folder tree to show updated counts
                    await self._load_folders()

            except Exception as e:
                await client.disconnect()
                raise e

        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")

    async def action_mark_junk(self) -> None:
        """Mark selected message(s) as junk, train classifier, and move to Junk folder."""
        message_list = self.query_one("#message-list", MessageList)
        messages = message_list.get_selected_messages()

        if not messages:
            self.notify("No message selected", severity="warning")
            return

        trained_count = 0
        moved_count = 0

        # Train classifier on each message if enabled
        if self._spam_config["train_on_move"] and self._spam_config["enabled"]:
            for message in messages:
                if not message.is_spam:
                    full_message = message
                    if self._repo and message.id:
                        full_message = await self._repo.get_message(message.id) or message
                    self._spam_classifier.train(full_message, is_spam=True)
                    trained_count += 1
            if trained_count > 0:
                self._spam_classifier.save()

        # Mark as spam locally and update database
        for message in messages:
            message.mark_spam()
            if self._repo and message.id:
                await self._repo.update_message_flags(message.id, message.flags)

        # Move to Junk folder on server if we have context
        if self._current_account and self._current_folder:
            # Don't move if already in Junk
            if self._current_folder.folder_type != FolderType.JUNK:
                valid_messages = [m for m in messages if m.uid]
                uids = [m.uid for m in valid_messages]

                if uids:
                    try:
                        junk_folder = await self._repo.get_folder_by_type(
                            self._current_account.id, FolderType.JUNK
                        )
                        if junk_folder:
                            client = IMAPClient(self._current_account)
                            await client.connect()
                            await client.move_messages(
                                self._current_folder.name,
                                junk_folder.name,
                                uids,
                            )
                            await client.disconnect()

                            # Update local database and remove from view
                            for message in valid_messages:
                                if self._repo and message.id:
                                    await self._repo.update_message_folder(message.id, junk_folder.id)
                                message_list.remove_message(message)
                                moved_count += 1

                            # Clear selection
                            message_list.clear_selection()

                            # Show next selected message in preview
                            preview = self.query_one("#message-preview", MessagePreview)
                            next_message = message_list.get_selected_message()
                            if next_message and next_message.id and self._repo:
                                full_next = await self._repo.get_message(next_message.id)
                                if full_next:
                                    await preview.show_message(full_next)
                            else:
                                await preview.clear()

                            if moved_count == 1:
                                self.notify("Moved to Junk")
                            else:
                                self.notify(f"Moved {moved_count} messages to Junk")
                            return
                    except Exception as e:
                        self.notify(f"Move failed: {e}", severity="error")

        # If we couldn't move, just update the display
        for message in messages:
            message_list.refresh_message(message)
        message_list.clear_selection()
        count = len(messages)
        if count == 1:
            self.notify("Marked as junk")
        else:
            self.notify(f"Marked {count} messages as junk")

    async def action_mark_not_junk(self) -> None:
        """Mark selected message(s) as not junk, train classifier, and move to Inbox."""
        message_list = self.query_one("#message-list", MessageList)
        messages = message_list.get_selected_messages()

        if not messages:
            self.notify("No message selected", severity="warning")
            return

        trained_count = 0
        moved_count = 0

        # Train classifier on each message if enabled
        if self._spam_config["train_on_move"] and self._spam_config["enabled"]:
            for message in messages:
                full_message = message
                if self._repo and message.id:
                    full_message = await self._repo.get_message(message.id) or message
                if message.is_spam:
                    # Untrain as spam first, then train as ham
                    self._spam_classifier.untrain(full_message, was_spam=True)
                self._spam_classifier.train(full_message, is_spam=False)
                trained_count += 1
            if trained_count > 0:
                self._spam_classifier.save()

        # Mark as not spam locally and update database
        for message in messages:
            message.mark_not_spam()
            if self._repo and message.id:
                await self._repo.update_message_flags(message.id, message.flags)

        # If in Junk folder, move to Inbox on server
        if self._current_account and self._current_folder:
            if self._current_folder.folder_type == FolderType.JUNK:
                valid_messages = [m for m in messages if m.uid]
                uids = [m.uid for m in valid_messages]

                if uids:
                    try:
                        inbox_folder = await self._repo.get_folder_by_type(
                            self._current_account.id, FolderType.INBOX
                        )
                        if inbox_folder:
                            client = IMAPClient(self._current_account)
                            await client.connect()
                            await client.move_messages(
                                self._current_folder.name,
                                inbox_folder.name,
                                uids,
                            )
                            await client.disconnect()

                            # Update local database and remove from view
                            for message in valid_messages:
                                if self._repo and message.id:
                                    await self._repo.update_message_folder(message.id, inbox_folder.id)
                                message_list.remove_message(message)
                                moved_count += 1

                            # Clear selection
                            message_list.clear_selection()

                            # Show next selected message in preview
                            preview = self.query_one("#message-preview", MessagePreview)
                            next_message = message_list.get_selected_message()
                            if next_message and next_message.id and self._repo:
                                full_next = await self._repo.get_message(next_message.id)
                                if full_next:
                                    await preview.show_message(full_next)
                            else:
                                await preview.clear()

                            if moved_count == 1:
                                self.notify("Moved to Inbox")
                            else:
                                self.notify(f"Moved {moved_count} messages to Inbox")
                            return
                    except Exception as e:
                        self.notify(f"Move failed: {e}", severity="error")

        # If we couldn't move, just update the display
        for message in messages:
            message_list.refresh_message(message)
        message_list.clear_selection()
        count = len(messages)
        if count == 1:
            self.notify("Marked as not junk")
        else:
            self.notify(f"Marked {count} messages as not junk")

    async def action_toggle_star(self) -> None:
        """Toggle star/flag on selected message(s)."""
        message_list = self.query_one("#message-list", MessageList)
        messages = message_list.get_selected_messages()

        if not messages:
            return

        starred_count = 0
        unstarred_count = 0

        for message in messages:
            message.toggle_flagged()
            if self._repo and message.id:
                await self._repo.update_message_flags(message.id, message.flags)
                message_list.refresh_message(message)
            if message.is_flagged:
                starred_count += 1
            else:
                unstarred_count += 1

        message_list.clear_selection()

        count = len(messages)
        if count == 1:
            status = "Starred" if messages[0].is_flagged else "Unstarred"
            self.notify(status)
        else:
            self.notify(f"Toggled star on {count} messages")

    async def action_mark_unread(self) -> None:
        """Mark selected message(s) as unread."""
        message_list = self.query_one("#message-list", MessageList)
        messages = message_list.get_selected_messages()

        if not messages:
            return

        marked_count = 0
        for message in messages:
            if message.is_read:
                message.mark_unread()
                if self._repo and message.id:
                    await self._repo.update_message_flags(message.id, message.flags)
                    message_list.refresh_message(message)
                marked_count += 1

        message_list.clear_selection()

        if marked_count == 1:
            self.notify("Marked as unread")
        elif marked_count > 1:
            self.notify(f"Marked {marked_count} messages as unread")

    def action_empty_folder(self) -> None:
        """Empty Trash or Junk folder - permanently delete all messages."""
        if not self._current_folder:
            self.notify("No folder selected", severity="warning")
            return

        # Only allow emptying Trash or Junk
        if self._current_folder.folder_type not in (FolderType.TRASH, FolderType.JUNK):
            self.notify("Can only empty Trash or Junk folders", severity="warning")
            return

        if not self._current_account:
            self.notify("No account context", severity="error")
            return

        folder_name = "Trash" if self._current_folder.folder_type == FolderType.TRASH else "Junk"

        # Get message count
        message_list = self.query_one("#message-list", MessageList)
        msg_count = len(message_list._messages)

        if msg_count == 0:
            self.notify(f"{folder_name} is already empty")
            return

        self.notify(f"Emptying {folder_name} ({msg_count} messages)...", timeout=10)
        self.update_status(f"Emptying {folder_name}...")

        # Run in background worker
        self._do_empty_folder(self._current_folder.id, self._current_folder.name, folder_name, msg_count)

    @work(exclusive=True, name="empty-folder")
    async def _do_empty_folder(self, folder_id: int, imap_folder_name: str, display_name: str, msg_count: int) -> None:
        """Background worker to empty a folder."""
        try:
            if self._repo and self._current_account:
                local_uids = await self._repo.get_local_uids(folder_id)

                if local_uids:
                    # Delete from server in batches
                    client = IMAPClient(self._current_account)
                    await client.connect()

                    try:
                        await client.delete_messages(
                            imap_folder_name,
                            list(local_uids)
                        )
                    finally:
                        await client.disconnect()

                # Delete all messages from local database
                await self._repo.delete_all_messages_in_folder(folder_id)

            # Clear the message list UI
            message_list = self.query_one("#message-list", MessageList)
            message_list.clear()
            message_list._messages.clear()

            # Clear the preview
            preview = self.query_one("#message-preview", MessagePreview)
            await preview.clear()

            # Update folder counts
            if self._current_folder and self._current_folder.id == folder_id:
                self._current_folder.total_messages = 0
                self._current_folder.unread_count = 0
                if self._repo:
                    await self._repo.save_folder(self._current_folder)

            # Refresh folder tree to show updated count
            folder_tree = self.query_one("#folder-tree", FolderTree)
            folder_tree.refresh()

            self.update_status(f"{display_name} emptied")
            self.notify(f"{display_name} emptied ({msg_count} messages deleted)")

        except Exception as e:
            self.update_status(f"Failed to empty {display_name}")
            self.notify(f"Failed to empty {display_name}: {e}", severity="error")

    async def action_save_attachments(self) -> None:
        """Save all attachments from current message to Downloads folder."""
        import os
        from pathlib import Path

        preview = self.query_one("#message-preview", MessagePreview)
        message = preview.current_message

        if not message:
            self.notify("No message selected", severity="warning")
            return

        if not message.has_attachments:
            self.notify("No attachments in this message", severity="warning")
            return

        # Get regular (non-inline) attachments
        attachments = message.regular_attachments
        if not attachments:
            self.notify("No downloadable attachments", severity="warning")
            return

        # Determine save directory (prefer ~/Downloads, fall back to home)
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.exists():
            downloads_dir = Path.home()

        saved_count = 0
        errors = []

        for att in attachments:
            if not att.data:
                errors.append(f"{att.filename}: no data")
                continue

            # Create safe filename (avoid path traversal)
            safe_name = os.path.basename(att.filename)
            if not safe_name:
                safe_name = f"attachment_{saved_count + 1}"

            # Handle duplicate filenames by adding a number
            save_path = downloads_dir / safe_name
            counter = 1
            while save_path.exists():
                stem = save_path.stem
                suffix = save_path.suffix
                save_path = downloads_dir / f"{stem}_{counter}{suffix}"
                counter += 1

            try:
                save_path.write_bytes(att.data)
                saved_count += 1
            except Exception as e:
                errors.append(f"{att.filename}: {e}")

        if saved_count > 0:
            if saved_count == 1:
                self.notify(f"Saved: {attachments[0].filename} to {downloads_dir}")
            else:
                self.notify(f"Saved {saved_count} attachments to {downloads_dir}")

        if errors:
            self.notify(f"Errors: {', '.join(errors)}", severity="error")

    def action_search(self) -> None:
        """Open search dialog."""
        folder_name = self._current_folder.name if self._current_folder else "INBOX"

        def handle_search_result(result: tuple[str, bool] | None) -> None:
            if result:
                query, search_all = result
                self._do_search(query, search_all)

        self.app.push_screen(SearchScreen(folder_name), handle_search_result)

    @work(exclusive=True)
    async def _do_search(self, query: str, search_all: bool) -> None:
        """Execute search and display results."""
        if not self._repo:
            return

        self._search_active = True
        self._search_query = query

        # Determine scope
        account_id = self._current_account.id if self._current_account and search_all else None
        folder_id = self._current_folder.id if self._current_folder and not search_all else None

        try:
            self.update_status(f"Searching for '{query}'...")

            # Execute FTS search
            results = await self._repo.search_messages(
                query,
                account_id=account_id,
                folder_id=folder_id,
                limit=100,
            )

            # Display results
            message_list = self.query_one("#message-list", MessageList)
            await message_list.load_messages(results)

            # Update status
            count = len(results)
            scope = "all folders" if search_all else (self._current_folder.name if self._current_folder else "current folder")
            if count == 0:
                self.update_status(f"No results for '{query}' in {scope}")
                self.notify(f"No messages found matching '{query}'", severity="warning")
            else:
                self.update_status(f"Found {count} message{'s' if count != 1 else ''} matching '{query}' in {scope} (Esc to clear)")
                self.notify(f"Found {count} result{'s' if count != 1 else ''}")

            # Clear preview
            preview = self.query_one("#message-preview", MessagePreview)
            await preview.clear()

        except Exception as e:
            self.update_status(f"Search failed: {e}")
            self.notify(f"Search error: {e}", severity="error")
            self._search_active = False
            self._search_query = ""

    async def action_clear_search(self) -> None:
        """Clear search results and return to folder view."""
        # If not in search mode, let escape do its normal thing (clear selection)
        if not self._search_active:
            # Clear selection if any
            message_list = self.query_one("#message-list", MessageList)
            if message_list.selection_count > 0:
                message_list.clear_selection()
            return

        # Clear search state
        self._search_active = False
        self._search_query = ""

        # Reload current folder
        if self._current_folder and self._repo:
            messages = await self._repo.get_messages(self._current_folder.id, limit=5000)
            message_list = self.query_one("#message-list", MessageList)
            await message_list.load_messages(messages)

            # Clear preview
            preview = self.query_one("#message-preview", MessagePreview)
            await preview.clear()

            self.update_status("Ready")
            self.notify("Search cleared")

    def action_focus_next_pane(self) -> None:
        """Move focus between folder tree and message list only."""
        focused = self.focused
        folder_tree = self.query_one("#folder-tree", FolderTree)
        message_list = self.query_one("#message-list", MessageList)

        if focused == folder_tree:
            message_list.focus()
        else:
            folder_tree.focus()

    def action_focus_prev_pane(self) -> None:
        """Move focus between folder tree and message list only."""
        # Same as next - just toggle between the two
        self.action_focus_next_pane()

    async def action_view_html(self) -> None:
        """View message HTML in browser (best experience with scroll + clickable links)."""
        preview = self.query_one("#message-preview", MessagePreview)
        message = preview.current_message

        if not message:
            self.notify("No message selected", severity="warning")
            return

        if not message.body_html:
            self.notify("No HTML content in this message", severity="warning")
            return

        # Open in browser - gives scrolling and clickable links
        await self._open_html_in_browser(message.body_html)

    async def action_view_image(self) -> None:
        """Render HTML as image using Playwright+Kitty (full fidelity view)."""
        preview = self.query_one("#message-preview", MessagePreview)
        message = preview.current_message

        if not message:
            self.notify("No message selected", severity="warning")
            return

        if not message.body_html:
            self.notify("No HTML content in this message", severity="warning")
            return

        self.notify("Rendering email...", timeout=2)

        try:
            # Import renderers
            from hawk_tui.rendering.browser import BrowserRenderer, BrowserRenderOptions
            from hawk_tui.rendering.images import ImageRenderer
            import os

            # Get terminal dimensions for sizing
            term_cols = os.get_terminal_size().columns
            pixel_width = min(term_cols * 10, 1200)  # Cap at reasonable width

            # Render HTML to PNG (async, while Textual still running)
            options = BrowserRenderOptions(
                viewport_width=pixel_width,
                viewport_height=800,
                dark_mode=True,
            )
            async with BrowserRenderer(options) as renderer:
                screenshot = await renderer.render(message.body_html)

            # Convert to Kitty escape sequence
            img_renderer = ImageRenderer()
            kitty_data = img_renderer.render_kitty_from_png(screenshot)

            # Now suspend Textual and display the image
            def display_image():
                import sys
                import termios
                import tty

                # Clear screen and show image
                print("\033[2J\033[H", end="")
                print(kitty_data, end="")
                sys.stdout.flush()

                # Show instructions
                print("\n\n[Press any key to return to Hawk-TUI]")

                # Wait for keypress
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    sys.stdin.read(1)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

            # Suspend Textual, display image, then resume
            with self.app.suspend():
                display_image()

        except ImportError as e:
            self.notify(
                f"Rendering unavailable: {e}\n"
                "Install: pip install playwright && playwright install chromium",
                severity="error",
                timeout=10,
            )
        except Exception as e:
            self.notify(f"Render failed: {e}", severity="error")

    async def _open_html_in_browser(self, html: str) -> None:
        """Open HTML in the default browser."""
        import tempfile
        import webbrowser

        # Add dark mode CSS wrapper
        dark_css = """
        <style>
            body {
                background-color: #1a1a1a !important;
                color: #e0e0e0 !important;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                padding: 20px;
                max-width: 800px;
                margin: 0 auto;
            }
            a { color: #6cb6ff !important; }
            img { max-width: 100%; }
        </style>
        """

        # Inject dark mode if not already in a full HTML doc
        if '<head' in html.lower():
            import re
            html = re.sub(r'(<head[^>]*>)', r'\1' + dark_css, html, count=1, flags=re.IGNORECASE)
        else:
            html = f"<!DOCTYPE html><html><head>{dark_css}</head><body>{html}</body></html>"

        # Write to temp file and open
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            f.write(html)
            temp_path = f.name

        webbrowser.open(f'file://{temp_path}')
        self.notify("Opened in browser")

    async def _render_and_display_html(self, html: str) -> None:
        """Render HTML with browser and display via Kitty graphics."""
        import sys
        import os

        try:
            from hawk_tui.rendering.browser import BrowserRenderer
            from hawk_tui.rendering.images import ImageRenderer

            # Clear screen
            print("\033[2J\033[H", end="")
            print("Rendering email with browser...\n")

            # Get terminal pixel size for proper rendering
            term_cols = os.get_terminal_size().columns

            # Calculate pixel width - assume ~10 pixels per character cell
            # This gives us a readable render that fills the terminal width
            pixel_width = term_cols * 10

            # Render HTML at a size that fills the terminal width
            from hawk_tui.rendering.browser import BrowserRenderOptions
            options = BrowserRenderOptions(
                viewport_width=pixel_width,
                viewport_height=800,  # Initial height, will expand for content
                dark_mode=True,
            )
            async with BrowserRenderer(options) as renderer:
                screenshot = await renderer.render(html)

            # Display via Kitty at native size (no scaling down)
            # This gives readable text - user can scroll in terminal if needed
            img_renderer = ImageRenderer()
            kitty_data = img_renderer.render_kitty_from_png(screenshot)

            # Clear screen and display
            print("\033[2J\033[H", end="")
            print(kitty_data, end="")
            sys.stdout.flush()

            # Wait for keypress
            print(f"\n\n[Press any key to return to Hawk-TUI]")
            # Read a single character
            import termios
            import tty
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        except ImportError as e:
            print(f"\nBrowser rendering not available: {e}")
            print("Install with: pip install playwright && playwright install chromium")
            input("\nPress Enter to continue...")
        except Exception as e:
            print(f"\nRendering error: {e}")
            input("\nPress Enter to continue...")
