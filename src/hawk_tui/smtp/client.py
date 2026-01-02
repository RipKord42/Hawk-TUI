# =============================================================================
# SMTP Client
# =============================================================================
# Provides async SMTP client for sending emails.
#
# Key responsibilities:
#   - Connection management with SSL/STARTTLS
#   - Building MIME messages (plain text, HTML, attachments)
#   - Sending emails
#   - Handling replies and forwards (proper headers)
#
# Uses aiosmtplib for async operations.
# =============================================================================

import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.encoders import encode_base64
from email.utils import formataddr, formatdate, make_msgid
from typing import TYPE_CHECKING

import aiosmtplib
import keyring

if TYPE_CHECKING:
    from hawk_tui.core import Account, Message

logger = logging.getLogger(__name__)


@dataclass
class EmailDraft:
    """
    Represents an email being composed.

    This is the working state of an email before it's sent.

    Attributes:
        to: List of recipient email addresses.
        cc: List of CC recipients.
        bcc: List of BCC recipients.
        subject: Email subject line.
        body_text: Plain text body.
        body_html: HTML body (optional).
        attachments: List of (filename, content_type, data) tuples.
        in_reply_to: Message-ID we're replying to (for threading).
        references: References header (for threading).
    """
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    attachments: list[tuple[str, str, bytes]] = field(default_factory=list)
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)


class SMTPClient:
    """
    Async SMTP client for sending emails.

    Usage:
        >>> client = SMTPClient(account)
        >>> await client.connect()
        >>> await client.send(draft)
        >>> await client.disconnect()

    Attributes:
        account: Account configuration with SMTP server details.
    """

    # Timeout for SMTP operations (seconds)
    TIMEOUT = 30

    def __init__(self, account: "Account") -> None:
        """
        Initialize the SMTP client.

        Args:
            account: Account configuration with SMTP server details.
        """
        self.account = account
        self._client: aiosmtplib.SMTP | None = None

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._client is not None and self._client.is_connected

    async def connect(self) -> bool:
        """
        Connect to the SMTP server.

        Returns:
            True if connection succeeded.

        Raises:
            SMTPConnectionError: If unable to connect.
            SMTPAuthenticationError: If authentication fails.
        """
        logger.info(f"Connecting to SMTP {self.account.smtp_host}:{self.account.smtp_port}")

        try:
            # Determine connection parameters based on security type
            use_tls = self.account.smtp_security == "ssl"
            start_tls = self.account.smtp_security == "starttls"

            # Create SMTP client
            self._client = aiosmtplib.SMTP(
                hostname=self.account.smtp_host,
                port=self.account.smtp_port,
                use_tls=use_tls,
                start_tls=start_tls,
                timeout=self.TIMEOUT,
            )

            # Connect
            await self._client.connect()
            logger.debug("SMTP connection established")

            # Authenticate
            await self._authenticate()

            logger.info(f"Successfully connected to SMTP {self.account.smtp_host}")
            return True

        except aiosmtplib.SMTPAuthenticationError as e:
            self._client = None
            raise SMTPAuthenticationError(
                f"SMTP authentication failed for {self.account.email}: {e}"
            ) from e
        except Exception as e:
            self._client = None
            raise SMTPConnectionError(
                f"Failed to connect to SMTP {self.account.smtp_host}:{self.account.smtp_port}: {e}"
            ) from e

    async def _authenticate(self) -> None:
        """
        Authenticate with the SMTP server using credentials from keyring.

        Raises:
            SMTPAuthenticationError: If login fails or password not found.
        """
        # Retrieve password from system keyring (same as IMAP)
        password = keyring.get_password(
            self.account.keyring_service,
            self.account.email
        )

        if not password:
            raise SMTPAuthenticationError(
                f"No password found in keyring for {self.account.email}. "
                f"Set it with: keyring set {self.account.keyring_service} {self.account.email}"
            )

        logger.debug(f"Authenticating as {self.account.email}")

        try:
            await self._client.login(self.account.email, password)
            logger.debug("SMTP authentication successful")
        except aiosmtplib.SMTPAuthenticationError as e:
            raise SMTPAuthenticationError(
                f"SMTP authentication failed for {self.account.email}: {e}"
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from the SMTP server."""
        if self._client and self._client.is_connected:
            try:
                logger.debug("Disconnecting from SMTP")
                await self._client.quit()
            except Exception as e:
                logger.warning(f"Error during SMTP disconnect: {e}")
            finally:
                self._client = None

    async def send(self, draft: EmailDraft) -> str:
        """
        Send an email.

        Args:
            draft: The email to send.

        Returns:
            Message-ID of the sent message.

        Raises:
            SendError: If sending fails.
        """
        if not self.is_connected:
            raise SendError("Not connected to SMTP server")

        if not draft.to:
            raise SendError("No recipients specified")

        try:
            # Build MIME message
            message = self._build_mime_message(draft)

            # Get all recipients
            all_recipients = draft.to + draft.cc + draft.bcc

            # Send
            logger.info(f"Sending email to {', '.join(draft.to)}")
            await self._client.send_message(message)

            message_id = message["Message-ID"]
            logger.info(f"Email sent successfully: {message_id}")

            return message_id

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            raise SendError(f"Failed to send email: {e}") from e

    def _build_mime_message(self, draft: EmailDraft) -> MIMEMultipart:
        """
        Build a MIME message from a draft.

        Handles:
            - Plain text only
            - HTML with plain text alternative
            - Attachments

        Returns:
            MIMEMultipart message ready to send.
        """
        # Determine message structure
        has_html = bool(draft.body_html)
        has_attachments = bool(draft.attachments)

        if has_attachments:
            # Mixed: contains body + attachments
            msg = MIMEMultipart("mixed")
            if has_html:
                # Body is alternative (text + html)
                body = MIMEMultipart("alternative")
                body.attach(MIMEText(draft.body_text, "plain", "utf-8"))
                body.attach(MIMEText(draft.body_html, "html", "utf-8"))
                msg.attach(body)
            else:
                # Body is plain text only
                msg.attach(MIMEText(draft.body_text, "plain", "utf-8"))

            # Add attachments
            for filename, content_type, data in draft.attachments:
                maintype, subtype = content_type.split("/", 1)
                part = MIMEBase(maintype, subtype)
                part.set_payload(data)
                encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=filename
                )
                msg.attach(part)
        elif has_html:
            # Alternative: text + html
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(draft.body_text, "plain", "utf-8"))
            msg.attach(MIMEText(draft.body_html, "html", "utf-8"))
        else:
            # Simple text message
            msg = MIMEMultipart()
            msg.attach(MIMEText(draft.body_text, "plain", "utf-8"))

        # Set headers
        msg["From"] = formataddr((self.account.display_name, self.account.email))
        msg["To"] = ", ".join(draft.to)
        if draft.cc:
            msg["Cc"] = ", ".join(draft.cc)
        # Note: BCC is not added to headers (that's the point of BCC)
        msg["Subject"] = draft.subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.account.email.split("@")[1])

        # Threading headers
        if draft.in_reply_to:
            msg["In-Reply-To"] = draft.in_reply_to
        if draft.references:
            msg["References"] = " ".join(draft.references)

        # User agent
        msg["X-Mailer"] = "Hawk-TUI"

        return msg

    def create_reply(
        self,
        original: "Message",
        *,
        reply_all: bool = False,
    ) -> EmailDraft:
        """
        Create a reply draft from an original message.

        Args:
            original: The message being replied to.
            reply_all: If True, include all recipients in reply.

        Returns:
            EmailDraft pre-populated for reply.
        """
        # Determine recipients
        to = [original.sender]
        cc = []

        if reply_all:
            our_email = self.account.email.lower()
            # Original To recipients stay in To (except ourselves)
            for recipient in original.recipients:
                if recipient.lower() != our_email and recipient.lower() != original.sender.lower():
                    to.append(recipient)
            # Original CC recipients stay in CC (except ourselves)
            for recipient in original.cc:
                if recipient.lower() != our_email:
                    cc.append(recipient)

        # Build subject
        subject = original.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Build references for threading
        references = []
        if original.in_reply_to:
            references.append(original.in_reply_to)
        if original.message_id:
            references.append(original.message_id)

        # Quote original message
        date_str = original.date_sent.strftime("%Y-%m-%d %H:%M") if original.date_sent else "unknown date"
        quote_header = f"\n\nOn {date_str}, {original.display_sender} wrote:\n"
        quoted_body = ""
        if original.body_text:
            # Add > prefix to each line
            for line in original.body_text.split("\n"):
                quoted_body += f"> {line}\n"

        body_text = quote_header + quoted_body

        return EmailDraft(
            to=to,
            cc=cc,
            subject=subject,
            body_text=body_text,
            in_reply_to=original.message_id,
            references=references,
        )

    def create_forward(self, original: "Message") -> EmailDraft:
        """
        Create a forward draft from an original message.

        Args:
            original: The message being forwarded.

        Returns:
            EmailDraft pre-populated for forwarding.
        """
        # Build subject
        subject = original.subject
        if not subject.lower().startswith("fwd:"):
            subject = f"Fwd: {subject}"

        # Build forwarded message body
        date_str = original.date_sent.strftime("%Y-%m-%d %H:%M") if original.date_sent else "unknown date"
        forward_header = (
            "\n\n---------- Forwarded message ----------\n"
            f"From: {original.display_sender} <{original.sender}>\n"
            f"Date: {date_str}\n"
            f"Subject: {original.subject}\n"
            f"To: {', '.join(original.recipients)}\n"
        )
        if original.cc:
            forward_header += f"Cc: {', '.join(original.cc)}\n"
        forward_header += "\n"

        body_text = forward_header + (original.body_text or "")

        # Include attachments from original message
        attachments = []
        if original.attachments:
            for att in original.attachments:
                if att.data:
                    attachments.append((att.filename, att.content_type, att.data))

        return EmailDraft(
            to=[],  # User fills in recipient
            subject=subject,
            body_text=body_text,
            attachments=attachments,
        )


class SMTPError(Exception):
    """Base exception for SMTP operations."""
    pass


class SMTPConnectionError(SMTPError):
    """Raised when unable to connect to SMTP server."""
    pass


class SMTPAuthenticationError(SMTPError):
    """Raised when SMTP authentication fails."""
    pass


class SendError(SMTPError):
    """Raised when email sending fails."""
    pass
