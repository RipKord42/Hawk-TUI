# =============================================================================
# SMTP Module
# =============================================================================
# Handles sending emails via SMTP (Simple Mail Transfer Protocol).
#
# Features:
#   - Connection with SSL/STARTTLS
#   - Message composition (reply, reply-all, forward)
#   - MIME message building (text, HTML, attachments)
#   - Sent message storage (copy to Sent folder via IMAP)
# =============================================================================

from hawk_tui.smtp.client import (
    SMTPClient,
    EmailDraft,
    SMTPError,
    SMTPConnectionError,
    SMTPAuthenticationError,
    SendError,
)

__all__ = [
    "SMTPClient",
    "EmailDraft",
    "SMTPError",
    "SMTPConnectionError",
    "SMTPAuthenticationError",
    "SendError",
]
