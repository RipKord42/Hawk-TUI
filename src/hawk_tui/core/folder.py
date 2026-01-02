# =============================================================================
# Folder Model
# =============================================================================
# Represents a mailbox folder (IMAP "mailbox"). Common folders include:
#   - INBOX: Primary incoming mail
#   - Sent: Copies of sent messages
#   - Drafts: Unsent message drafts
#   - Trash: Deleted messages
#   - Junk/Spam: Messages flagged as spam
#
# IMAP allows arbitrary folder hierarchies, so users may have custom folders
# like "Work/Projects/Alpha" or "Receipts/2024".
# =============================================================================

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto


class FolderType(Enum):
    """
    Standard folder types that have special meaning in email clients.

    These map to IMAP SPECIAL-USE attributes (RFC 6154) when available,
    or are inferred from common naming conventions.
    """
    INBOX = auto()      # Primary incoming mail
    SENT = auto()       # Sent messages
    DRAFTS = auto()     # Unsent drafts
    TRASH = auto()      # Deleted messages (before permanent deletion)
    JUNK = auto()       # Spam/junk mail
    ARCHIVE = auto()    # Archived messages
    OTHER = auto()      # User-created or unrecognized folders


@dataclass
class Folder:
    """
    Represents a mailbox folder in an email account.

    Attributes:
        name: The folder's display name (e.g., "INBOX", "Work/Projects").
              For nested folders, this is typically the full path.
        account_id: Foreign key to the Account this folder belongs to.

        folder_type: The semantic type of this folder (inbox, sent, etc.).
                     Used to apply special behaviors (e.g., auto-move sent
                     messages to Sent folder).

        uidvalidity: IMAP UIDVALIDITY value. This is a critical concept:
                     - Each folder has a UIDVALIDITY value
                     - Each message has a UID within that folder
                     - If UIDVALIDITY changes, ALL cached UIDs are invalid
                     - This happens when the mailbox is rebuilt/recreated
                     We must check this on every sync and re-download everything
                     if it changes.

        delimiter: The hierarchy delimiter for this folder (usually "/" or ".").
                   Used when creating subfolders.

        total_messages: Total number of messages in the folder (from server).
        unread_count: Number of unread messages (for UI display).

        last_sync: Timestamp of the last successful sync operation.
        id: Database primary key. None until saved to storage.

    Example:
        >>> folder = Folder(
        ...     name="INBOX",
        ...     account_id=1,
        ...     folder_type=FolderType.INBOX,
        ...     uidvalidity=1234567890,
        ... )
    """

    # Folder identification
    name: str                                   # Display name / path
    account_id: int                             # Foreign key to Account

    # Folder classification
    folder_type: FolderType = FolderType.OTHER  # Semantic folder type

    # IMAP synchronization state
    # UIDVALIDITY is crucial: if this changes, our cached UIDs are worthless
    # and we need to re-sync the entire folder. This happens rarely but we
    # must handle it correctly to avoid data corruption.
    uidvalidity: int | None = None
    delimiter: str = "/"                        # Folder hierarchy separator

    # Message counts (cached from server)
    total_messages: int = 0
    unread_count: int = 0

    # Sync tracking
    last_sync: datetime | None = None

    # Database field
    id: int | None = None                       # Primary key (None until saved)

    @property
    def is_special(self) -> bool:
        """Returns True if this is a standard special folder (not OTHER)."""
        return self.folder_type != FolderType.OTHER

    @property
    def parent_path(self) -> str | None:
        """
        Returns the parent folder path, or None if this is a top-level folder.

        Example:
            >>> Folder(name="Work/Projects/Alpha", ...).parent_path
            "Work/Projects"
            >>> Folder(name="INBOX", ...).parent_path
            None
        """
        if self.delimiter in self.name:
            return self.name.rsplit(self.delimiter, 1)[0]
        return None

    @property
    def display_name(self) -> str:
        """
        Returns just the folder name without parent path.

        Example:
            >>> Folder(name="Work/Projects/Alpha", ...).display_name
            "Alpha"
        """
        if self.delimiter in self.name:
            return self.name.rsplit(self.delimiter, 1)[1]
        return self.name

    @classmethod
    def detect_type(cls, folder_name: str) -> FolderType:
        """
        Attempt to detect the folder type from its name.

        This handles common naming conventions across email providers.
        Ideally we'd use IMAP SPECIAL-USE attributes, but not all servers
        support them.

        Args:
            folder_name: The IMAP folder name to classify.

        Returns:
            The detected FolderType, or OTHER if unrecognized.
        """
        # Normalize for comparison
        name_lower = folder_name.lower()

        # Check for standard folder names
        # Different providers use different conventions...
        if name_lower == "inbox":
            return FolderType.INBOX
        elif name_lower in ("sent", "sent mail", "sent items", "[gmail]/sent mail"):
            return FolderType.SENT
        elif name_lower in ("drafts", "draft", "[gmail]/drafts"):
            return FolderType.DRAFTS
        elif name_lower in ("trash", "deleted", "deleted items", "[gmail]/trash"):
            return FolderType.TRASH
        elif name_lower in ("junk", "spam", "junk mail", "[gmail]/spam"):
            return FolderType.JUNK
        elif name_lower in ("archive", "all mail", "[gmail]/all mail"):
            return FolderType.ARCHIVE

        return FolderType.OTHER

    def __str__(self) -> str:
        """Human-readable representation."""
        unread_indicator = f" ({self.unread_count})" if self.unread_count > 0 else ""
        return f"{self.name}{unread_indicator}"

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"Folder(name={self.name!r}, type={self.folder_type.name}, "
            f"messages={self.total_messages}, unread={self.unread_count})"
        )
