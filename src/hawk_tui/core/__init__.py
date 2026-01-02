# =============================================================================
# Hawk-TUI Core Module
# =============================================================================
# This module contains the core domain models for Hawk-TUI. These are pure
# Python dataclasses with no external dependencies — they can be imported
# anywhere without causing circular dependency issues.
#
# The core models represent the fundamental concepts in an email client:
#   - Account: An email account (IMAP/SMTP credentials)
#   - Folder: A mailbox folder (Inbox, Sent, etc.)
#   - Message: An individual email message
#   - Attachment: A file attached to a message
# =============================================================================

from hawk_tui.core.account import Account
from hawk_tui.core.folder import Folder, FolderType
from hawk_tui.core.message import Attachment, Message, MessageFlags

__all__ = [
    "Account",
    "Folder",
    "FolderType",
    "Message",
    "MessageFlags",
    "Attachment",
]
