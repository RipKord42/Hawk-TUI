# =============================================================================
# Message Model
# =============================================================================
# Represents an email message. This is the most complex model in the system
# as emails contain:
#   - Headers (From, To, Subject, Date, Message-ID, etc.)
#   - Body in potentially multiple formats (plain text, HTML, or both)
#   - Attachments (files, inline images)
#   - IMAP metadata (UID, flags)
#   - Local metadata (spam score, sync state)
#
# Emails are complex beasts. A single email can contain multiple "parts"
# (MIME multipart) with different content types. Our storage layer handles
# parsing this; the Message model represents the simplified view we work with.
# =============================================================================

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntFlag


class MessageFlags(IntFlag):
    """
    Email message flags, stored as a bitmask for efficient storage.

    Standard IMAP flags (RFC 3501):
        - SEEN: Message has been read
        - ANSWERED: Message has been replied to
        - FLAGGED: User-flagged as important (usually shown as a star)
        - DELETED: Marked for deletion (will be purged on EXPUNGE)
        - DRAFT: Message is a draft (not yet sent)

    Hawk-TUI custom flags:
        - SPAM: Message classified as spam by our local filter

    Usage:
        # Set flags
        msg.flags = MessageFlags.SEEN | MessageFlags.FLAGGED

        # Check flags
        if msg.flags & MessageFlags.SEEN:
            print("Message has been read")

        # Add a flag
        msg.flags |= MessageFlags.ANSWERED

        # Remove a flag
        msg.flags &= ~MessageFlags.FLAGGED
    """
    NONE = 0            # No flags set
    SEEN = 1 << 0       # Message has been read (\\Seen)
    ANSWERED = 1 << 1   # Message has been replied to (\\Answered)
    FLAGGED = 1 << 2    # User-flagged / starred (\\Flagged)
    DELETED = 1 << 3    # Marked for deletion (\\Deleted)
    DRAFT = 1 << 4      # Is a draft (\\Draft)
    SPAM = 1 << 5       # Classified as spam (local flag, not synced to IMAP)


@dataclass
class Attachment:
    """
    Represents a file attached to an email message.

    Attachments can be:
        - Regular attachments: Files the user explicitly attached
        - Inline attachments: Images embedded in HTML (referenced by Content-ID)

    Attributes:
        filename: Original filename of the attachment.
        content_type: MIME type (e.g., "application/pdf", "image/png").
        size: Size in bytes.
        content_id: For inline images, the Content-ID used in HTML <img> tags.
                    HTML references these as: <img src="cid:content_id">
        data: The actual attachment data (bytes). May be None if not yet loaded
              (we can lazy-load attachments to save memory).
        id: Database primary key.
        message_id: Foreign key to the parent Message.

    Example:
        >>> attachment = Attachment(
        ...     filename="report.pdf",
        ...     content_type="application/pdf",
        ...     size=1024000,
        ... )
    """
    filename: str
    content_type: str
    size: int

    # For inline images (embedded in HTML)
    content_id: str | None = None       # Content-ID for <img src="cid:...">
    is_inline: bool = False             # True if embedded in HTML body

    # The actual data (may be lazy-loaded)
    data: bytes | None = None

    # Database fields
    id: int | None = None
    message_id: int | None = None       # Foreign key to Message

    @property
    def is_image(self) -> bool:
        """Returns True if this attachment is an image."""
        return self.content_type.startswith("image/")

    @property
    def human_size(self) -> str:
        """
        Returns a human-readable file size.

        Examples:
            - 500 -> "500 B"
            - 1500 -> "1.5 KB"
            - 1500000 -> "1.4 MB"
        """
        size = self.size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}" if size != int(size) else f"{int(size)} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


@dataclass
class Message:
    """
    Represents an email message.

    This is the core data structure for emails in Hawk-TUI. It contains:
        - Envelope information (from, to, subject, date)
        - Message body in multiple formats (text and/or HTML)
        - IMAP synchronization state (UID, flags)
        - Local metadata (spam score)

    Threading note:
        Emails can be threaded together using Message-ID, In-Reply-To, and
        References headers. The 'message_id' field is the RFC Message-ID
        (not our database ID), and 'in_reply_to' / 'references' help build
        conversation threads.

    Attributes:
        folder_id: Foreign key to the Folder containing this message.
        uid: IMAP UID - unique identifier within a folder. Combined with
             the folder's UIDVALIDITY, this uniquely identifies a message.

        message_id: RFC 5322 Message-ID header (e.g., "<abc123@example.com>").
                    Used for threading and deduplication.
        in_reply_to: Message-ID of the message this replies to.
        references: List of Message-IDs in the thread (for threading).

        subject: Email subject line.
        sender: The "From" address (single address).
        sender_name: Display name of the sender (e.g., "John Doe").
        recipients: List of "To" addresses.
        cc: List of "CC" addresses.
        bcc: List of "BCC" addresses (usually empty for received mail).

        date_sent: When the message was sent (from Date header).
        date_received: When we received/synced the message.

        flags: Message flags (seen, answered, flagged, etc.).
        spam_score: Local spam classifier score (0.0 = ham, 1.0 = spam).

        body_text: Plain text version of the body.
        body_html: HTML version of the body (the interesting part!).

        attachments: List of file attachments.

        id: Database primary key.

    Example:
        >>> message = Message(
        ...     folder_id=1,
        ...     uid=12345,
        ...     subject="Hello World",
        ...     sender="alice@example.com",
        ...     sender_name="Alice",
        ...     recipients=["bob@example.com"],
        ...     body_text="Hello!",
        ... )
    """

    # Folder association and IMAP identity
    folder_id: int | None = None
    uid: int = 0                        # IMAP UID (unique within folder)

    # Message identification (for threading)
    message_id: str = ""                # RFC Message-ID header
    in_reply_to: str = ""               # Message-ID this replies to
    references: list[str] = field(default_factory=list)  # Thread history

    # Envelope information
    subject: str = ""
    sender: str = ""                    # From email address
    sender_name: str = ""               # From display name
    recipients: list[str] = field(default_factory=list)   # To addresses
    cc: list[str] = field(default_factory=list)           # CC addresses
    bcc: list[str] = field(default_factory=list)          # BCC addresses

    # Timestamps
    date_sent: datetime | None = None       # When message was sent
    date_received: datetime | None = None   # When we synced it

    # Flags and classification
    flags: MessageFlags = MessageFlags.NONE
    spam_score: float = 0.0             # 0.0 = ham, 1.0 = definitely spam

    # Message body - may have text, HTML, or both
    body_text: str = ""                 # Plain text body
    body_html: str = ""                 # HTML body (our main focus!)

    # For storage of original message (optional, for debugging/compliance)
    raw_headers: str = ""               # Original headers as string

    # Attachments (populated separately, may be lazy-loaded)
    attachments: list[Attachment] = field(default_factory=list)

    # Database field
    id: int | None = None               # Primary key

    # -------------------------------------------------------------------------
    # Convenience properties for checking flags
    # -------------------------------------------------------------------------

    @property
    def is_read(self) -> bool:
        """Returns True if the message has been read (SEEN flag)."""
        return bool(self.flags & MessageFlags.SEEN)

    @property
    def is_answered(self) -> bool:
        """Returns True if the message has been replied to."""
        return bool(self.flags & MessageFlags.ANSWERED)

    @property
    def is_flagged(self) -> bool:
        """Returns True if the message is starred/flagged."""
        return bool(self.flags & MessageFlags.FLAGGED)

    @property
    def is_deleted(self) -> bool:
        """Returns True if the message is marked for deletion."""
        return bool(self.flags & MessageFlags.DELETED)

    @property
    def is_draft(self) -> bool:
        """Returns True if this is a draft message."""
        return bool(self.flags & MessageFlags.DRAFT)

    @property
    def is_spam(self) -> bool:
        """Returns True if the message is classified as spam."""
        return bool(self.flags & MessageFlags.SPAM)

    # -------------------------------------------------------------------------
    # Convenience methods
    # -------------------------------------------------------------------------

    @property
    def has_html(self) -> bool:
        """Returns True if the message has an HTML body."""
        return bool(self.body_html.strip())

    @property
    def has_attachments(self) -> bool:
        """Returns True if the message has any attachments."""
        return len(self.attachments) > 0

    @property
    def inline_images(self) -> list[Attachment]:
        """Returns list of inline images (embedded in HTML)."""
        return [a for a in self.attachments if a.is_inline and a.is_image]

    @property
    def regular_attachments(self) -> list[Attachment]:
        """Returns list of non-inline attachments."""
        return [a for a in self.attachments if not a.is_inline]

    @property
    def display_sender(self) -> str:
        """
        Returns the best display string for the sender.
        Prefers sender_name if available, falls back to email address.
        """
        if self.sender_name:
            return self.sender_name
        return self.sender

    @property
    def preview(self) -> str:
        """
        Returns a short preview of the message body (first ~100 chars).
        Used for message list display.
        """
        text = self.body_text or ""
        # Remove excessive whitespace
        text = " ".join(text.split())
        if len(text) > 100:
            return text[:97] + "..."
        return text

    def mark_read(self) -> None:
        """Mark this message as read."""
        self.flags |= MessageFlags.SEEN

    def mark_unread(self) -> None:
        """Mark this message as unread."""
        self.flags &= ~MessageFlags.SEEN

    def mark_spam(self) -> None:
        """Mark this message as spam."""
        self.flags |= MessageFlags.SPAM

    def mark_not_spam(self) -> None:
        """Mark this message as not spam (ham)."""
        self.flags &= ~MessageFlags.SPAM

    def toggle_flagged(self) -> None:
        """Toggle the flagged/starred status."""
        self.flags ^= MessageFlags.FLAGGED

    def __str__(self) -> str:
        """Human-readable representation."""
        read_marker = " " if self.is_read else "*"
        flag_marker = "!" if self.is_flagged else " "
        return f"{read_marker}{flag_marker} {self.display_sender}: {self.subject}"

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"Message(uid={self.uid}, subject={self.subject!r}, "
            f"from={self.sender!r}, flags={self.flags})"
        )
