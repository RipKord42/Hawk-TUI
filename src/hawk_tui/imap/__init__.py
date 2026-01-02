# =============================================================================
# IMAP Module
# =============================================================================
# Handles all IMAP (Internet Message Access Protocol) operations:
#   - Connecting to IMAP servers with SSL/STARTTLS
#   - Fetching folder lists
#   - Syncing messages (full sync and incremental)
#   - Managing message flags (read, flagged, deleted)
#   - IMAP IDLE for push notifications
#
# This module uses aioimaplib for async IMAP operations, which allows
# the UI to remain responsive during network operations.
# =============================================================================

from hawk_tui.imap.client import (
    IMAPClient,
    IMAPError,
    IMAPConnectionError,
    IMAPAuthenticationError,
    ConnectionState,
)
from hawk_tui.imap.sync import (
    SyncManager,
    SyncStatus,
    SyncProgress,
    SyncResult,
)
from hawk_tui.imap.idle import (
    IdleWorker,
    IdleEvent,
)

__all__ = [
    # Client
    "IMAPClient",
    "IMAPError",
    "IMAPConnectionError",
    "IMAPAuthenticationError",
    "ConnectionState",
    # Sync
    "SyncManager",
    "SyncStatus",
    "SyncProgress",
    "SyncResult",
    # IDLE
    "IdleWorker",
    "IdleEvent",
]
