# =============================================================================
# IMAP Client
# =============================================================================
# Provides an async IMAP client wrapper around aioimaplib.
#
# Key responsibilities:
#   - Connection management (connect, disconnect, reconnect)
#   - Authentication (supports STARTTLS and SSL)
#   - Folder operations (list, select, create, delete)
#   - Message operations (fetch, flag, move, delete)
#   - IDLE support for push notifications
#
# Design notes:
#   - All methods are async to avoid blocking the UI
#   - Automatic reconnection on connection loss
#   - Proper handling of IMAP quirks (UIDVALIDITY, etc.)
# =============================================================================

import asyncio
import email
import email.header
import email.utils
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message as EmailMessage
from typing import TYPE_CHECKING, Any, Callable

import keyring
from aioimaplib import aioimaplib

if TYPE_CHECKING:
    from hawk_tui.core import Account

from hawk_tui.core import Folder, FolderType, Message, MessageFlags, Attachment

# Set up logging for this module
logger = logging.getLogger(__name__)


def _quote_folder_name(name: str) -> str:
    """
    Quote an IMAP folder name if it contains special characters.

    IMAP folder names with spaces or special characters must be quoted.
    This function wraps folder names in double quotes and escapes
    any internal quotes or backslashes.

    Args:
        name: The folder name to quote.

    Returns:
        Properly quoted folder name for IMAP commands.
    """
    # If name contains spaces, special chars, or quotes, it needs quoting
    if ' ' in name or '"' in name or '\\' in name or any(c in name for c in '(){}[]'):
        # Escape backslashes and quotes
        escaped = name.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return name


@dataclass
class ConnectionState:
    """
    Tracks the current state of an IMAP connection.

    Attributes:
        connected: Whether we have an active connection.
        authenticated: Whether we've successfully logged in.
        selected_folder: Currently selected folder, if any.
        capabilities: Server capabilities (from CAPABILITY response).
        uidvalidity: UIDVALIDITY of currently selected folder.
    """
    connected: bool = False
    authenticated: bool = False
    selected_folder: str | None = None
    capabilities: list[str] = field(default_factory=list)
    uidvalidity: int | None = None


class IMAPClient:
    """
    Async IMAP client for Hawk-TUI.

    This class wraps aioimaplib and provides a higher-level interface
    for email operations.

    Usage:
        >>> client = IMAPClient(account)
        >>> await client.connect()
        >>> folders = await client.list_folders()
        >>> messages = await client.fetch_messages("INBOX", limit=50)
        >>> await client.disconnect()

    Attributes:
        account: The Account configuration for this connection.
        state: Current connection state.
    """

    # Timeout for IMAP operations (seconds)
    TIMEOUT = 30

    def __init__(self, account: "Account") -> None:
        """
        Initialize the IMAP client.

        Args:
            account: Account configuration with IMAP server details.
        """
        self.account = account
        self.state = ConnectionState()
        self._client: aioimaplib.IMAP4_SSL | aioimaplib.IMAP4 | None = None

    @property
    def is_connected(self) -> bool:
        """Check if client is connected and authenticated."""
        return self.state.connected and self.state.authenticated and self._client is not None

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(self) -> bool:
        """
        Establish connection to the IMAP server.

        Handles both SSL and STARTTLS connections based on account config.

        Returns:
            True if connection and authentication succeeded.

        Raises:
            IMAPConnectionError: If unable to connect to server.
            IMAPAuthenticationError: If login fails.
        """
        logger.info(f"Connecting to {self.account.imap_host}:{self.account.imap_port}")

        try:
            # Create connection based on security type
            if self.account.imap_security == "ssl":
                # Direct SSL connection (usually port 993)
                self._client = aioimaplib.IMAP4_SSL(
                    host=self.account.imap_host,
                    port=self.account.imap_port,
                    timeout=self.TIMEOUT,
                )
            else:
                # Plain connection, will upgrade with STARTTLS (usually port 143)
                self._client = aioimaplib.IMAP4(
                    host=self.account.imap_host,
                    port=self.account.imap_port,
                    timeout=self.TIMEOUT,
                )

            # Wait for connection to be established
            await self._client.wait_hello_from_server()
            self.state.connected = True
            logger.debug("Connected, checking capabilities")

            # Get server capabilities
            # aioimaplib stores capabilities in client.protocol.capabilities
            # after wait_hello_from_server() is called
            self.state.capabilities = list(self._client.protocol.capabilities)
            logger.debug(f"Server capabilities: {self.state.capabilities}")

            # Upgrade to TLS if using STARTTLS
            if self.account.imap_security == "starttls":
                if not self._client.has_capability("STARTTLS"):
                    raise IMAPConnectionError("Server does not support STARTTLS")
                logger.debug("Upgrading to TLS via STARTTLS")
                await self._client.starttls()

            # Authenticate
            await self._authenticate()

            logger.info(f"Successfully connected to {self.account.imap_host}")
            return True

        except asyncio.TimeoutError as e:
            self.state.connected = False
            raise IMAPConnectionError(
                f"Connection timed out to {self.account.imap_host}:{self.account.imap_port}"
            ) from e
        except OSError as e:
            self.state.connected = False
            raise IMAPConnectionError(
                f"Failed to connect to {self.account.imap_host}:{self.account.imap_port}: {e}"
            ) from e

    async def _authenticate(self) -> None:
        """
        Authenticate with the IMAP server using credentials from keyring.

        Raises:
            IMAPAuthenticationError: If login fails or password not found.
        """
        # Retrieve password from system keyring
        password = keyring.get_password(
            self.account.keyring_service,
            self.account.email
        )

        if not password:
            raise IMAPAuthenticationError(
                f"No password found in keyring for {self.account.email}. "
                f"Set it with: keyring set {self.account.keyring_service} {self.account.email}"
            )

        logger.debug(f"Authenticating as {self.account.email}")

        # Login
        response = await self._client.login(self.account.email, password)

        if response.result != "OK":
            raise IMAPAuthenticationError(
                f"Authentication failed for {self.account.email}: {response.lines}"
            )

        self.state.authenticated = True
        logger.debug("Authentication successful")

    async def disconnect(self) -> None:
        """
        Gracefully disconnect from the IMAP server.

        Sends LOGOUT command and closes the connection.
        """
        if self._client and self.state.connected:
            try:
                logger.debug("Sending LOGOUT")
                await self._client.logout()
            except Exception as e:
                logger.warning(f"Error during logout: {e}")
            finally:
                self._client = None
                self.state = ConnectionState()

    async def ensure_connected(self) -> None:
        """
        Ensure we have an active connection, reconnecting if necessary.

        Raises:
            IMAPConnectionError: If reconnection fails.
        """
        if not self.state.connected or not self._client:
            await self.connect()

    def _parse_capabilities(self, response) -> list[str]:
        """Parse capabilities from CAPABILITY response."""
        capabilities = []
        for line in response.lines:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            # Capabilities are space-separated
            parts = line.upper().split()
            capabilities.extend(parts)
        return capabilities

    # =========================================================================
    # Folder Operations
    # =========================================================================

    async def list_folders(self, include_status: bool = True) -> list[Folder]:
        """
        Fetch list of all folders/mailboxes.

        Args:
            include_status: If True, also fetch message counts for each folder.
                           This makes additional STATUS requests (slower but complete).

        Returns:
            List of Folder objects with metadata.
        """
        await self.ensure_connected()

        logger.debug("Listing folders")

        # Use LIST command to get all folders
        # Pattern "" "*" means all folders from root
        response = await self._client.list('""', "*")

        if response.result != "OK":
            logger.error(f"Failed to list folders: {response.lines}")
            return []

        folders = []
        for line in response.lines:
            folder = self._parse_folder_line(line)
            if folder:
                folders.append(folder)

        # Optionally enrich folders with message counts
        if include_status:
            for folder in folders:
                try:
                    status = await self.get_folder_status(folder.name)
                    folder.total_messages = status.get("MESSAGES", 0)
                    folder.unread_count = status.get("UNSEEN", 0)
                    folder.uidvalidity = status.get("UIDVALIDITY")
                except Exception as e:
                    logger.warning(f"Could not get status for {folder.name}: {e}")

        logger.debug(f"Found {len(folders)} folders")
        return folders

    def _parse_folder_line(self, line: bytes | str) -> Folder | None:
        """
        Parse a single LIST response line into a Folder object.

        LIST response format:
            (\\HasNoChildren) "/" "INBOX"
            (\\HasNoChildren \\Sent) "/" "Sent"
        """
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")

        # Skip empty lines and status/completion messages
        if not line or "completed" in line.lower():
            return None

        # Parse the LIST response
        # Format: (flags) "delimiter" "name"
        match = re.match(r'\(([^)]*)\)\s+"([^"]+)"\s+"?([^"]+)"?', line)
        if not match:
            # Try alternate format without quotes around name
            match = re.match(r'\(([^)]*)\)\s+"([^"]+)"\s+(.+)', line)
            if not match:
                logger.warning(f"Could not parse folder line: {line}")
                return None

        flags_str, delimiter, name = match.groups()
        flags = flags_str.split() if flags_str else []

        # Detect folder type from SPECIAL-USE flags or name
        folder_type = self._detect_folder_type(name, flags)

        return Folder(
            name=name.strip('"'),
            account_id=0,  # Will be set by caller
            folder_type=folder_type,
            delimiter=delimiter,
        )

    def _detect_folder_type(self, name: str, flags: list[str]) -> FolderType:
        """
        Detect folder type from SPECIAL-USE flags or folder name.

        SPECIAL-USE attributes (RFC 6154):
            \\All, \\Archive, \\Drafts, \\Flagged, \\Junk, \\Sent, \\Trash
        """
        # Check SPECIAL-USE flags first
        flags_upper = [f.upper() for f in flags]

        if "\\INBOX" in flags_upper or name.upper() == "INBOX":
            return FolderType.INBOX
        elif "\\SENT" in flags_upper:
            return FolderType.SENT
        elif "\\DRAFTS" in flags_upper:
            return FolderType.DRAFTS
        elif "\\TRASH" in flags_upper:
            return FolderType.TRASH
        elif "\\JUNK" in flags_upper:
            return FolderType.JUNK
        elif "\\ARCHIVE" in flags_upper or "\\ALL" in flags_upper:
            return FolderType.ARCHIVE

        # Fall back to name-based detection
        return Folder.detect_type(name)

    async def select_folder(self, folder_name: str, readonly: bool = False) -> dict:
        """
        Select a folder for subsequent operations.

        Args:
            folder_name: Name of the folder to select.
            readonly: If True, open in read-only mode (EXAMINE).

        Returns:
            Dictionary with folder status (EXISTS, RECENT, UIDVALIDITY, etc.)

        Raises:
            IMAPError: If folder selection fails.
        """
        await self.ensure_connected()

        # If already selected, get status without reselecting
        if self.state.selected_folder == folder_name:
            # Use STATUS to get message counts without reselecting
            status_response = await self.get_folder_status(folder_name)
            return {
                "EXISTS": status_response.get("MESSAGES", 0),
                "RECENT": status_response.get("RECENT", 0),
                "UNSEEN": status_response.get("UNSEEN", 0),
                "UIDVALIDITY": status_response.get("UIDVALIDITY"),
                "UIDNEXT": status_response.get("UIDNEXT"),
            }

        logger.debug(f"Selecting folder: {folder_name}")

        # Quote folder name for IMAP if it contains spaces or special chars
        quoted_name = _quote_folder_name(folder_name)

        if readonly:
            response = await self._client.examine(quoted_name)
        else:
            response = await self._client.select(quoted_name)

        if response.result != "OK":
            raise IMAPError(f"Failed to select folder '{folder_name}': {response.lines}")

        # Parse folder status from response
        status = self._parse_select_response(response)

        self.state.selected_folder = folder_name
        self.state.uidvalidity = status.get("UIDVALIDITY")

        logger.debug(f"Selected folder: {folder_name}, {status}")
        return status

    def _parse_select_response(self, response) -> dict:
        """Parse SELECT/EXAMINE response into a status dictionary."""
        status = {}

        for line in response.lines:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")

            # Parse EXISTS
            match = re.search(r"(\d+)\s+EXISTS", line, re.IGNORECASE)
            if match:
                status["EXISTS"] = int(match.group(1))

            # Parse RECENT
            match = re.search(r"(\d+)\s+RECENT", line, re.IGNORECASE)
            if match:
                status["RECENT"] = int(match.group(1))

            # Parse UIDVALIDITY
            match = re.search(r"UIDVALIDITY\s+(\d+)", line, re.IGNORECASE)
            if match:
                status["UIDVALIDITY"] = int(match.group(1))

            # Parse UIDNEXT
            match = re.search(r"UIDNEXT\s+(\d+)", line, re.IGNORECASE)
            if match:
                status["UIDNEXT"] = int(match.group(1))

            # Parse UNSEEN
            match = re.search(r"UNSEEN\s+(\d+)", line, re.IGNORECASE)
            if match:
                status["UNSEEN"] = int(match.group(1))

        return status

    async def get_folder_status(self, folder_name: str) -> dict:
        """
        Get status of a folder without selecting it.

        Args:
            folder_name: Name of the folder.

        Returns:
            Dictionary with MESSAGES, RECENT, UNSEEN, UIDNEXT, UIDVALIDITY.
        """
        await self.ensure_connected()

        # Quote folder name for IMAP if it contains spaces or special chars
        quoted_name = _quote_folder_name(folder_name)

        response = await self._client.status(
            quoted_name,
            "(MESSAGES RECENT UNSEEN UIDNEXT UIDVALIDITY)"
        )

        if response.result != "OK":
            return {}

        # Parse STATUS response
        status = {}
        for line in response.lines:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")

            # Extract values from parentheses
            match = re.search(r"\((.*)\)", line)
            if match:
                items = match.group(1).split()
                for i in range(0, len(items) - 1, 2):
                    key = items[i].upper()
                    try:
                        status[key] = int(items[i + 1])
                    except (ValueError, IndexError):
                        pass

        return status

    # =========================================================================
    # Message Fetching
    # =========================================================================

    async def get_folder_uids(self, folder_name: str) -> set[int]:
        """
        Get all message UIDs in a folder.

        This is a lightweight operation (fetches only UIDs) used to compare
        server state with local state for detecting moved/deleted messages.

        Args:
            folder_name: Name of the folder.

        Returns:
            Set of UIDs present on the server.
        """
        import sys

        await self.ensure_connected()
        status = await self.select_folder(folder_name)

        # Check if folder is empty
        total = status.get("EXISTS", 0)
        if total == 0:
            return set()

        # For large folders, aioimaplib's recursive response parser can hit
        # Python's recursion limit. Temporarily increase it for this operation.
        old_limit = sys.getrecursionlimit()
        if total > 1000:
            sys.setrecursionlimit(max(old_limit, total + 1000))

        try:
            # Fetch only UIDs for all messages (lightweight)
            response = await self._client.fetch("1:*", "(UID)")

            if response.result != "OK":
                logger.error(f"UID fetch failed: {response.lines}")
                return set()

            # Parse UIDs from "N FETCH (UID xxx)" responses
            uids = set()
            uid_pattern = re.compile(r"UID\s+(\d+)")
            for line in response.lines:
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                match = uid_pattern.search(str(line))
                if match:
                    uids.add(int(match.group(1)))

            logger.debug(f"Found {len(uids)} UIDs in {folder_name}")
            return uids

        finally:
            # Restore original recursion limit
            if total > 1000:
                sys.setrecursionlimit(old_limit)

    async def fetch_messages(
        self,
        folder_name: str,
        *,
        uids: list[int] | None = None,
        limit: int | None = None,
        since_uid: int | None = None,
        fetch_body: bool = False,
    ) -> list[Message]:
        """
        Fetch messages from a folder.

        Args:
            folder_name: Name of the folder to fetch from.
            uids: Specific UIDs to fetch (if None, fetches based on limit).
            limit: Maximum number of messages to fetch (newest first).
            since_uid: Only fetch messages with UID > this value.
            fetch_body: If True, fetch full body (slower). Otherwise headers only.

        Returns:
            List of Message objects.
        """
        await self.ensure_connected()

        # Select the folder
        status = await self.select_folder(folder_name)
        total_messages = status.get("EXISTS", 0)

        if total_messages == 0:
            return []

        # Build FETCH command items
        # We always fetch UID, envelope and flags
        # Body is optional and much slower
        if fetch_body:
            fetch_items = "(UID FLAGS ENVELOPE BODY.PEEK[])"
        else:
            fetch_items = "(UID FLAGS ENVELOPE BODY.PEEK[HEADER])"

        # Determine which messages to fetch
        # Note: UIDs can be sparse (deleted messages leave gaps), so for
        # "most recent N" we use sequence numbers, not UIDs.
        use_uid_fetch = True
        if uids:
            # Specific UIDs requested - use UID FETCH
            msg_range = ",".join(str(u) for u in uids)
        elif since_uid:
            # Messages after a specific UID - use UID FETCH
            msg_range = f"{since_uid + 1}:*"
        elif limit:
            # Fetch the most recent 'limit' messages
            # Use sequence numbers (not UIDs) since UIDs can be sparse
            start = max(1, total_messages - limit + 1)
            msg_range = f"{start}:*"
            use_uid_fetch = False  # Use regular FETCH with sequence numbers
        else:
            # Fetch all (use sequence numbers for consistency)
            msg_range = "1:*"
            use_uid_fetch = False

        logger.debug(f"Fetching messages: {msg_range} from {folder_name} (UID={use_uid_fetch})")

        # Use UID FETCH or regular FETCH based on the request type
        if use_uid_fetch:
            response = await self._client.uid("FETCH", msg_range, fetch_items)
        else:
            response = await self._client.fetch(msg_range, fetch_items)

        if response.result != "OK":
            logger.error(f"Fetch failed: {response.lines}")
            return []

        # Parse response into Message objects
        messages = self._parse_fetch_response(response, fetch_body)

        logger.debug(f"Fetched {len(messages)} messages")
        return messages

    def _parse_fetch_response(
        self,
        response,
        include_body: bool = False
    ) -> list[Message]:
        """
        Parse FETCH response into Message objects.

        IMAP responses can have literal data (indicated by {N}) that continues
        on the next line(s). aioimaplib returns items as a mix of text lines
        and raw byte literals. We need to:
        1. Group response items by message
        2. Capture body content (returned as separate byte items after {N} markers)
        3. Parse envelope data from text portions
        """
        messages = []

        # First pass: decode all lines and group by message
        # Each message starts with "N FETCH (" pattern
        # Body content follows BODY[] {N} markers as raw bytes
        message_groups: list[dict] = []
        current_text = ""
        current_body: bytes | None = None
        expect_literal = False
        literal_size = 0

        for item in response.lines:
            # Convert everything to bytes first
            if isinstance(item, (bytes, bytearray)):
                item_bytes = bytes(item)
            else:
                item_bytes = str(item).encode("utf-8")

            # If we're expecting literal data (body content)
            if expect_literal and len(item_bytes) > 0:
                # This should be the body content
                # Check if size roughly matches expected (allow for encoding differences)
                if len(item_bytes) >= literal_size * 0.8 or len(item_bytes) > 100:
                    current_body = item_bytes
                    expect_literal = False
                    continue

            # Decode to string for pattern matching
            line = item_bytes.decode("utf-8", errors="replace")

            # Check if this starts a new FETCH response
            fetch_match = re.match(r'^(\d+)\s+FETCH\s*\(', line, re.IGNORECASE)
            if fetch_match:
                # Save previous message if exists
                if current_text:
                    message_groups.append({
                        "text": current_text,
                        "body": current_body
                    })
                current_text = line
                current_body = None
                expect_literal = False

                # Check if this line ends with a BODY[] literal marker
                body_literal_match = re.search(r'BODY\[\]?\s*\{(\d+)\}\s*$', line, re.IGNORECASE)
                if body_literal_match:
                    literal_size = int(body_literal_match.group(1))
                    expect_literal = True

            elif current_text:
                # Check if this line ends with a BODY[] literal marker
                body_literal_match = re.search(r'BODY\[\]?\s*\{(\d+)\}\s*$', line, re.IGNORECASE)
                if body_literal_match:
                    literal_size = int(body_literal_match.group(1))
                    expect_literal = True
                    current_text += " " + line.strip()
                # Check if this is body content (large bytes with email headers)
                elif (len(item_bytes) > 200 and
                      (b"Return-Path:" in item_bytes or
                       b"Received:" in item_bytes or
                       b"MIME-Version:" in item_bytes or
                       b"Content-Type:" in item_bytes or
                       b"From:" in item_bytes)):
                    current_body = item_bytes
                elif current_text.rstrip().endswith("}"):
                    # Previous line ended with {N} literal marker
                    # This could be body content or envelope literal
                    if len(item_bytes) > 200:
                        # Large content - likely body
                        current_body = item_bytes
                    else:
                        # Small content - inline into text
                        escaped = f'"{line}"'.replace('\\', '\\\\')
                        current_text = re.sub(r'\{[\d]+\}\s*$', escaped, current_text)
                else:
                    # Continuation line - append to current message
                    current_text += " " + line.strip()

        # Save last message
        if current_text:
            message_groups.append({
                "text": current_text,
                "body": current_body
            })

        # Second pass: parse each message group
        for group in message_groups:
            text = group["text"]

            # Skip status lines like "Fetch completed"
            if "completed" in text.lower() and "FETCH" not in text.upper():
                continue
            if not re.search(r'\d+\s+FETCH\s*\(', text, re.IGNORECASE):
                continue

            data = self._parse_fetch_line(text)
            if data and "uid" in data:
                if group["body"]:
                    data["body_raw"] = group["body"]
                msg = self._build_message(data, include_body)
                if msg:
                    messages.append(msg)

        return messages

    def _parse_fetch_line(self, line: str | bytes | bytearray) -> dict[str, Any] | None:
        """Parse a single FETCH response line."""
        # Handle bytes, bytearray, and str
        # aioimaplib can return any of these types in responses
        if isinstance(line, (bytes, bytearray)):
            line = line.decode("utf-8", errors="replace")

        if not line or "FETCH" not in line.upper():
            return None

        data: dict[str, Any] = {}

        # Extract UID
        uid_match = re.search(r"UID\s+(\d+)", line, re.IGNORECASE)
        if uid_match:
            data["uid"] = int(uid_match.group(1))

        # Extract FLAGS
        flags_match = re.search(r"FLAGS\s*\(([^)]*)\)", line, re.IGNORECASE)
        if flags_match:
            data["flags"] = self._parse_flags(flags_match.group(1))

        # Extract ENVELOPE (complex structure)
        # The envelope contains: date, subject, from, sender, reply-to, to, cc, bcc, in-reply-to, message-id
        envelope_match = re.search(r"ENVELOPE\s*\((.+)\)", line, re.IGNORECASE)
        if envelope_match:
            data["envelope"] = self._parse_envelope(envelope_match.group(1))

        return data if data else None

    def _parse_flags(self, flags_str: str) -> MessageFlags:
        """Convert IMAP flags string to MessageFlags."""
        result = MessageFlags.NONE

        flags_upper = flags_str.upper()
        if "\\SEEN" in flags_upper:
            result |= MessageFlags.SEEN
        if "\\ANSWERED" in flags_upper:
            result |= MessageFlags.ANSWERED
        if "\\FLAGGED" in flags_upper:
            result |= MessageFlags.FLAGGED
        if "\\DELETED" in flags_upper:
            result |= MessageFlags.DELETED
        if "\\DRAFT" in flags_upper:
            result |= MessageFlags.DRAFT

        return result

    def _parse_envelope(self, envelope_str: str) -> dict[str, Any]:
        """
        Parse IMAP ENVELOPE structure.

        Format: (date subject ((from-name NIL from-user from-host))
                 sender reply-to to cc bcc in-reply-to message-id)
        """
        # This is complex because it contains nested structures
        # For now, we'll do basic parsing
        envelope: dict[str, Any] = {}

        # Try to extract key fields using patterns
        # This is simplified - a full parser would handle the nested structure

        # The envelope is NIL-separated with quoted strings and addresses
        parts = self._tokenize_envelope(envelope_str)

        if len(parts) >= 2:
            # First element is date
            envelope["date"] = self._clean_envelope_string(parts[0])
            # Second is subject
            envelope["subject"] = self._decode_header(
                self._clean_envelope_string(parts[1])
            )

        if len(parts) >= 3:
            # Third is FROM address list
            envelope["from"] = self._parse_address_list(parts[2])

        if len(parts) >= 6:
            # Sixth is TO address list
            envelope["to"] = self._parse_address_list(parts[5])

        if len(parts) >= 7:
            # Seventh is CC
            envelope["cc"] = self._parse_address_list(parts[6])

        if len(parts) >= 10:
            # Tenth is Message-ID
            envelope["message_id"] = self._clean_envelope_string(parts[9])

        if len(parts) >= 9:
            # Ninth is In-Reply-To
            envelope["in_reply_to"] = self._clean_envelope_string(parts[8])

        return envelope

    def _tokenize_envelope(self, s: str) -> list[str]:
        """
        Tokenize an envelope string, handling nested parentheses and quotes.
        """
        tokens = []
        current = ""
        depth = 0
        in_quote = False

        for char in s:
            if char == '"' and depth == 0:
                in_quote = not in_quote
                current += char
            elif char == "(" and not in_quote:
                depth += 1
                current += char
            elif char == ")" and not in_quote:
                depth -= 1
                current += char
            elif char == " " and depth == 0 and not in_quote:
                if current:
                    tokens.append(current)
                    current = ""
            else:
                current += char

        if current:
            tokens.append(current)

        return tokens

    def _clean_envelope_string(self, s: str) -> str:
        """Clean up an envelope string value."""
        if not s or s.upper() == "NIL":
            return ""
        # Remove surrounding quotes
        s = s.strip('"')
        return s

    def _parse_address_list(self, addr_str: str) -> list[dict[str, str]]:
        """Parse an address list from envelope."""
        if not addr_str or addr_str.upper() == "NIL":
            return []

        addresses = []

        # Address format: ((name NIL user host)(name NIL user host)...)
        # Find all address tuples
        pattern = r'\(([^()]*?)\s+NIL\s+([^()]*?)\s+([^()]*?)\)'
        matches = re.findall(pattern, addr_str, re.IGNORECASE)

        for match in matches:
            name, user, host = match
            name = self._clean_envelope_string(name)
            user = self._clean_envelope_string(user)
            host = self._clean_envelope_string(host)

            if user and host:
                addr = {
                    "name": self._decode_header(name),
                    "email": f"{user}@{host}"
                }
                addresses.append(addr)

        return addresses

    def _decode_header(self, value: str) -> str:
        """Decode RFC 2047 encoded header value."""
        if not value:
            return ""
        try:
            decoded_parts = email.header.decode_header(value)
            result = ""
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    result += part.decode(charset or "utf-8", errors="replace")
                else:
                    result += part
            return result
        except Exception:
            return value

    def _build_message(
        self,
        data: dict[str, Any],
        include_body: bool = False
    ) -> Message | None:
        """Build a Message object from parsed FETCH data."""
        if "uid" not in data:
            return None

        envelope = data.get("envelope", {})

        # Parse date and normalize to UTC for consistent sorting
        date_str = envelope.get("date", "")
        date_sent = None
        if date_str:
            try:
                date_tuple = email.utils.parsedate_to_datetime(date_str)
                # Convert to UTC for consistent database sorting
                if date_tuple.tzinfo is not None:
                    from datetime import timezone
                    date_sent = date_tuple.astimezone(timezone.utc)
                else:
                    # Assume UTC if no timezone
                    date_sent = date_tuple
            except Exception:
                pass

        # Extract sender info
        from_list = envelope.get("from", [])
        sender = from_list[0]["email"] if from_list else ""
        sender_name = from_list[0].get("name", "") if from_list else ""

        # Extract recipients
        to_list = envelope.get("to", [])
        recipients = [a["email"] for a in to_list]

        cc_list = envelope.get("cc", [])
        cc = [a["email"] for a in cc_list]

        # Parse body if present
        body_text = ""
        body_html = ""
        attachments: list[Attachment] = []

        if include_body and "body_raw" in data:
            body_text, body_html, attachments = self._parse_body(data["body_raw"])

        return Message(
            uid=data["uid"],
            message_id=envelope.get("message_id", ""),
            in_reply_to=envelope.get("in_reply_to", ""),
            subject=envelope.get("subject", ""),
            sender=sender,
            sender_name=sender_name,
            recipients=recipients,
            cc=cc,
            date_sent=date_sent,
            date_received=datetime.now(),
            flags=data.get("flags", MessageFlags.NONE),
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
        )

    def _parse_body(
        self,
        raw_body: bytes
    ) -> tuple[str, str, list[Attachment]]:
        """
        Parse raw email body into text, HTML, and attachments.

        Args:
            raw_body: Raw RFC822 message bytes.

        Returns:
            Tuple of (body_text, body_html, attachments).
        """
        body_text = ""
        body_html = ""
        attachments: list[Attachment] = []

        try:
            msg = email.message_from_bytes(raw_body)

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    # Skip multipart containers
                    if part.is_multipart():
                        continue

                    # Check if it's an attachment
                    if "attachment" in content_disposition:
                        att = self._extract_attachment(part)
                        if att:
                            attachments.append(att)
                    elif content_type == "text/plain" and not body_text:
                        body_text = self._decode_part(part)
                    elif content_type == "text/html" and not body_html:
                        body_html = self._decode_part(part)
                    elif content_type.startswith("image/"):
                        # Inline image
                        att = self._extract_attachment(part)
                        if att:
                            att.is_inline = True
                            att.content_id = part.get("Content-ID", "").strip("<>")
                            attachments.append(att)
            else:
                # Simple message
                content_type = msg.get_content_type()
                if content_type == "text/plain":
                    body_text = self._decode_part(msg)
                elif content_type == "text/html":
                    body_html = self._decode_part(msg)

        except Exception as e:
            logger.error(f"Error parsing message body: {e}")
            # Return raw text as fallback
            body_text = raw_body.decode("utf-8", errors="replace")

        return body_text, body_html, attachments

    def _decode_part(self, part: EmailMessage) -> str:
        """Decode a message part to string."""
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            # Try to detect charset
            charset = part.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                return payload.decode("utf-8", errors="replace")
        return str(payload) if payload else ""

    def _extract_attachment(self, part: EmailMessage) -> Attachment | None:
        """Extract attachment from message part."""
        filename = part.get_filename()
        if not filename:
            # Generate filename from content type
            content_type = part.get_content_type()
            ext = content_type.split("/")[-1] if "/" in content_type else "bin"
            filename = f"attachment.{ext}"

        # Decode filename if encoded
        filename = self._decode_header(filename)

        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return None

        return Attachment(
            filename=filename,
            content_type=part.get_content_type(),
            size=len(payload),
            data=payload,
        )

    async def fetch_message_body(self, folder_name: str, uid: int) -> Message | None:
        """
        Fetch the full body of a specific message.

        Args:
            folder_name: Folder containing the message.
            uid: IMAP UID of the message.

        Returns:
            Message with full body, or None if not found.
        """
        messages = await self.fetch_messages(
            folder_name,
            uids=[uid],
            fetch_body=True
        )
        return messages[0] if messages else None

    # =========================================================================
    # Flag Operations
    # =========================================================================

    async def set_flags(
        self,
        folder_name: str,
        uids: list[int],
        flags: list[str],
        *,
        add: bool = True,
    ) -> None:
        """
        Add or remove flags on messages.

        Args:
            folder_name: Folder containing the messages.
            uids: UIDs of messages to modify.
            flags: Flags to add/remove (e.g., ["\\Seen", "\\Flagged"]).
            add: If True, add flags. If False, remove flags.
        """
        await self.ensure_connected()
        await self.select_folder(folder_name)

        uid_set = ",".join(str(u) for u in uids)
        flags_str = " ".join(flags)

        if add:
            command = f"+FLAGS ({flags_str})"
        else:
            command = f"-FLAGS ({flags_str})"

        logger.debug(f"Setting flags on {uid_set}: {command}")
        response = await self._client.uid("STORE", uid_set, command)

        if response.result != "OK":
            raise IMAPError(f"Failed to set flags: {response.lines}")

    async def mark_read(self, folder_name: str, uids: list[int]) -> None:
        """Mark messages as read."""
        await self.set_flags(folder_name, uids, ["\\Seen"], add=True)

    async def mark_unread(self, folder_name: str, uids: list[int]) -> None:
        """Mark messages as unread."""
        await self.set_flags(folder_name, uids, ["\\Seen"], add=False)

    async def mark_flagged(self, folder_name: str, uids: list[int]) -> None:
        """Mark messages as flagged/starred."""
        await self.set_flags(folder_name, uids, ["\\Flagged"], add=True)

    async def mark_unflagged(self, folder_name: str, uids: list[int]) -> None:
        """Remove flag/star from messages."""
        await self.set_flags(folder_name, uids, ["\\Flagged"], add=False)

    # =========================================================================
    # Message Operations
    # =========================================================================

    async def move_messages(
        self,
        source_folder: str,
        dest_folder: str,
        uids: list[int],
    ) -> None:
        """
        Move messages from one folder to another.

        Uses MOVE command if supported, otherwise COPY + DELETE.
        Processes in batches to avoid command size limits.

        Args:
            source_folder: Source folder name.
            dest_folder: Destination folder name.
            uids: UIDs of messages to move.
        """
        await self.ensure_connected()
        await self.select_folder(source_folder)

        # Quote destination folder name for IMAP
        quoted_dest = _quote_folder_name(dest_folder)

        # Process in batches of 100 to avoid command size limits
        batch_size = 100
        for i in range(0, len(uids), batch_size):
            batch = uids[i:i + batch_size]
            uid_set = ",".join(str(u) for u in batch)

            # Check if server supports MOVE
            if self._client.has_capability("MOVE"):
                logger.debug(f"Moving {len(batch)} messages to {dest_folder} using MOVE")
                response = await self._client.uid("MOVE", uid_set, quoted_dest)
                if response.result != "OK":
                    raise IMAPError(f"Move failed: {response.lines}")
            else:
                # Fall back to COPY + DELETE + EXPUNGE
                logger.debug(f"Moving {len(batch)} messages to {dest_folder} using COPY+DELETE")

                # Copy
                response = await self._client.uid("COPY", uid_set, quoted_dest)
                if response.result != "OK":
                    raise IMAPError(f"Copy failed: {response.lines}")

                # Mark as deleted
                await self.set_flags(source_folder, batch, ["\\Deleted"], add=True)

                # Expunge after each batch
                await self._client.expunge()

    async def delete_messages(self, folder_name: str, uids: list[int]) -> None:
        """
        Mark messages as deleted and expunge.

        For large numbers of messages, processes in batches to avoid
        command size limits and timeouts.

        Args:
            folder_name: Folder containing the messages.
            uids: UIDs of messages to delete.
        """
        await self.ensure_connected()
        await self.select_folder(folder_name)

        # Process in batches of 100 to avoid command size limits
        batch_size = 100
        for i in range(0, len(uids), batch_size):
            batch = uids[i:i + batch_size]
            # Mark batch as deleted
            await self.set_flags(folder_name, batch, ["\\Deleted"], add=True)

        # Expunge to permanently delete all marked messages
        logger.debug(f"Expunging {len(uids)} deleted messages in {folder_name}")
        await self._client.expunge()

    async def copy_messages(
        self,
        source_folder: str,
        dest_folder: str,
        uids: list[int],
    ) -> None:
        """
        Copy messages to another folder.

        Args:
            source_folder: Source folder name.
            dest_folder: Destination folder name.
            uids: UIDs of messages to copy.
        """
        await self.ensure_connected()
        await self.select_folder(source_folder)

        uid_set = ",".join(str(u) for u in uids)

        # Quote destination folder name for IMAP
        quoted_dest = _quote_folder_name(dest_folder)

        response = await self._client.uid("COPY", uid_set, quoted_dest)
        if response.result != "OK":
            raise IMAPError(f"Copy failed: {response.lines}")

    # =========================================================================
    # IDLE Support
    # =========================================================================

    def supports_idle(self) -> bool:
        """Check if server supports IDLE command."""
        if not self._client:
            return False
        return self._client.has_capability("IDLE")

    async def idle_start(self, folder_name: str) -> bool:
        """
        Enter IDLE mode on a folder.

        This selects the folder and starts IDLE. Use idle_wait() to wait
        for changes, then idle_done() to exit IDLE mode.

        Args:
            folder_name: Folder to monitor.

        Returns:
            True if IDLE started successfully.
        """
        await self.ensure_connected()

        if not self.supports_idle():
            logger.warning("Server does not support IDLE")
            return False

        await self.select_folder(folder_name)

        logger.debug(f"Entering IDLE mode on {folder_name}")
        await self._client.idle_start()
        return True

    async def idle_wait(self, timeout: float = 29 * 60) -> list[str]:
        """
        Wait for IDLE notifications from server.

        Blocks until the server sends a notification (EXISTS, EXPUNGE, etc.)
        or until the timeout expires.

        Args:
            timeout: Maximum seconds to wait (default 29 minutes per RFC).

        Returns:
            List of notification strings from server, or empty list on timeout.
        """
        if not self._client:
            return []

        try:
            # aioimaplib wait_server_push returns the response
            msg = await asyncio.wait_for(
                self._client.wait_server_push(),
                timeout=timeout,
            )

            if msg:
                # Parse the response lines
                notifications = []
                for line in msg:
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    notifications.append(str(line))
                logger.debug(f"IDLE notifications: {notifications}")
                return notifications

        except asyncio.TimeoutError:
            logger.debug("IDLE timeout - refreshing connection")
        except Exception as e:
            logger.warning(f"IDLE wait error: {e}")

        return []

    async def idle_done(self) -> None:
        """
        Exit IDLE mode.

        Must be called after idle_wait() returns to properly close IDLE.
        """
        if self._client:
            try:
                self._client.idle_done()
                # Wait for the idle task to complete
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.warning(f"Error ending IDLE: {e}")


# =============================================================================
# Exceptions
# =============================================================================

class IMAPError(Exception):
    """Base exception for IMAP operations."""
    pass


class IMAPConnectionError(IMAPError):
    """Raised when unable to connect to IMAP server."""
    pass


class IMAPAuthenticationError(IMAPError):
    """Raised when IMAP authentication fails."""
    pass
