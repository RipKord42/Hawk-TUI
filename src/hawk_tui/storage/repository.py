# =============================================================================
# Repository - Data Access Layer
# =============================================================================
# Provides high-level CRUD operations for all domain models.
#
# This is the main interface between the application logic and the database.
# It handles:
#   - Converting between domain models and database rows
#   - Complex queries (search, filtering, sorting)
#   - Transaction management
#
# All methods are async for non-blocking database access.
# =============================================================================

import json
from datetime import datetime
from typing import TYPE_CHECKING

from hawk_tui.core import Account, Folder, FolderType, Message, MessageFlags, Attachment

if TYPE_CHECKING:
    from hawk_tui.storage.database import Database


class Repository:
    """
    Data access layer for Hawk-TUI.

    Provides CRUD operations for all domain models, abstracting away
    the SQLite details.

    Usage:
        >>> repo = Repository(database)
        >>> accounts = await repo.get_all_accounts()
        >>> messages = await repo.get_messages(folder_id=1, limit=50)
        >>> await repo.save_message(message)

    Attributes:
        db: Database instance for executing queries.
    """

    def __init__(self, db: "Database") -> None:
        """
        Initialize the repository.

        Args:
            db: Connected Database instance.
        """
        self.db = db

    # =========================================================================
    # Account Operations
    # =========================================================================

    async def get_all_accounts(self) -> list[Account]:
        """
        Get all configured accounts.

        Returns:
            List of Account objects.
        """
        async with self.db.conn.execute(
            "SELECT * FROM accounts ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_account(row) for row in rows]

    async def get_account(self, account_id: int) -> Account | None:
        """
        Get an account by ID.

        Args:
            account_id: Primary key of the account.

        Returns:
            Account if found, None otherwise.
        """
        async with self.db.conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_account(row) if row else None

    async def get_account_by_name(self, name: str) -> Account | None:
        """
        Get an account by its unique name.

        Args:
            name: Account name (e.g., "personal", "work").

        Returns:
            Account if found, None otherwise.
        """
        async with self.db.conn.execute(
            "SELECT * FROM accounts WHERE name = ?", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_account(row) if row else None

    async def save_account(self, account: Account) -> Account:
        """
        Save an account (insert or update).

        Args:
            account: Account to save.

        Returns:
            Saved account with ID populated.
        """
        if account.id is None:
            # Insert new account
            cursor = await self.db.conn.execute(
                """INSERT INTO accounts
                   (name, email, display_name, imap_host, imap_port, imap_security,
                    smtp_host, smtp_port, smtp_security, enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (account.name, account.email, account.display_name,
                 account.imap_host, account.imap_port, account.imap_security,
                 account.smtp_host, account.smtp_port, account.smtp_security,
                 account.enabled)
            )
            account.id = cursor.lastrowid
        else:
            # Update existing account
            await self.db.conn.execute(
                """UPDATE accounts SET
                   name=?, email=?, display_name=?, imap_host=?, imap_port=?,
                   imap_security=?, smtp_host=?, smtp_port=?, smtp_security=?, enabled=?
                   WHERE id=?""",
                (account.name, account.email, account.display_name,
                 account.imap_host, account.imap_port, account.imap_security,
                 account.smtp_host, account.smtp_port, account.smtp_security,
                 account.enabled, account.id)
            )
        await self.db.conn.commit()
        return account

    async def delete_account(self, account_id: int) -> None:
        """
        Delete an account and all its data.

        Args:
            account_id: ID of account to delete.
        """
        # CASCADE will handle folders and messages
        await self.db.conn.execute(
            "DELETE FROM accounts WHERE id = ?", (account_id,)
        )
        await self.db.conn.commit()

    def _row_to_account(self, row) -> Account:
        """Convert a database row to an Account object."""
        return Account(
            id=row[0],
            name=row[1],
            email=row[2],
            display_name=row[3] or "",
            imap_host=row[4],
            imap_port=row[5],
            imap_security=row[6],
            smtp_host=row[7],
            smtp_port=row[8],
            smtp_security=row[9],
            enabled=bool(row[10]),
        )

    # =========================================================================
    # Folder Operations
    # =========================================================================

    async def get_folders(self, account_id: int) -> list[Folder]:
        """
        Get all folders for an account.

        Args:
            account_id: Account to get folders for.

        Returns:
            List of Folder objects.
        """
        async with self.db.conn.execute(
            "SELECT * FROM folders WHERE account_id = ? ORDER BY name",
            (account_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_folder(row) for row in rows]

    async def get_folder(self, folder_id: int) -> Folder | None:
        """
        Get a folder by ID.

        Args:
            folder_id: Primary key of the folder.

        Returns:
            Folder if found, None otherwise.
        """
        async with self.db.conn.execute(
            "SELECT * FROM folders WHERE id = ?", (folder_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_folder(row) if row else None

    async def save_folder(self, folder: Folder) -> Folder:
        """
        Save a folder (insert or update).

        Args:
            folder: Folder to save.

        Returns:
            Saved folder with ID populated.
        """
        if folder.id is None:
            cursor = await self.db.conn.execute(
                """INSERT INTO folders
                   (account_id, name, folder_type, uidvalidity, delimiter,
                    total_messages, unread_count, last_sync)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (folder.account_id, folder.name, folder.folder_type.name.lower(),
                 folder.uidvalidity, folder.delimiter, folder.total_messages,
                 folder.unread_count,
                 folder.last_sync.isoformat() if folder.last_sync else None)
            )
            folder.id = cursor.lastrowid
        else:
            await self.db.conn.execute(
                """UPDATE folders SET
                   name=?, folder_type=?, uidvalidity=?, delimiter=?,
                   total_messages=?, unread_count=?, last_sync=?
                   WHERE id=?""",
                (folder.name, folder.folder_type.name.lower(), folder.uidvalidity,
                 folder.delimiter, folder.total_messages, folder.unread_count,
                 folder.last_sync.isoformat() if folder.last_sync else None,
                 folder.id)
            )
        await self.db.conn.commit()
        return folder

    async def get_folder_by_name(
        self,
        account_id: int,
        folder_name: str,
    ) -> Folder | None:
        """
        Get a folder by account ID and folder name.

        Args:
            account_id: Account ID.
            folder_name: IMAP folder name (e.g., "INBOX").

        Returns:
            Folder if found, None otherwise.
        """
        async with self.db.conn.execute(
            "SELECT * FROM folders WHERE account_id = ? AND name = ?",
            (account_id, folder_name)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_folder(row) if row else None

    async def delete_folder(self, folder_id: int) -> None:
        """
        Delete a folder and all its messages.

        Args:
            folder_id: ID of folder to delete.
        """
        # CASCADE will handle messages
        await self.db.conn.execute(
            "DELETE FROM folders WHERE id = ?", (folder_id,)
        )
        await self.db.conn.commit()

    async def get_folder_by_type(
        self,
        account_id: int,
        folder_type: FolderType,
    ) -> Folder | None:
        """
        Get a folder by account ID and folder type.

        Args:
            account_id: Account ID.
            folder_type: Type of folder to find (e.g., FolderType.TRASH).

        Returns:
            Folder if found, None otherwise.
        """
        async with self.db.conn.execute(
            "SELECT * FROM folders WHERE account_id = ? AND folder_type = ?",
            (account_id, folder_type.name.lower())
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_folder(row) if row else None

    async def delete_message(self, message_id: int) -> None:
        """
        Delete a single message by ID.

        Args:
            message_id: ID of message to delete.
        """
        await self.db.conn.execute(
            "DELETE FROM messages WHERE id = ?", (message_id,)
        )
        await self.db.conn.commit()

    async def update_message_folder(self, message_id: int, folder_id: int) -> None:
        """
        Move a message to a different folder in the local database.

        Args:
            message_id: ID of message to move.
            folder_id: ID of destination folder.
        """
        await self.db.conn.execute(
            "UPDATE messages SET folder_id = ? WHERE id = ?",
            (folder_id, message_id),
        )
        await self.db.conn.commit()

    def _row_to_folder(self, row) -> Folder:
        """Convert a database row to a Folder object."""
        return Folder(
            id=row[0],
            account_id=row[1],
            name=row[2],
            folder_type=FolderType[row[3].upper()],
            uidvalidity=row[4],
            delimiter=row[5] or "/",
            total_messages=row[6] or 0,
            unread_count=row[7] or 0,
            last_sync=datetime.fromisoformat(row[8]) if row[8] else None,
        )

    # =========================================================================
    # Message Operations
    # =========================================================================

    async def get_messages(
        self,
        folder_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[Message]:
        """
        Get messages from a folder.

        Args:
            folder_id: Folder to get messages from.
            limit: Maximum number of messages to return.
            offset: Number of messages to skip (for pagination).
            unread_only: If True, only return unread messages.

        Returns:
            List of Message objects (without body, for efficiency).
        """
        query = "SELECT * FROM messages WHERE folder_id = ?"
        params: list = [folder_id]

        if unread_only:
            # Check if SEEN flag is NOT set
            query += " AND (flags & ?) = 0"
            params.append(MessageFlags.SEEN)

        # Sort by date_sent, handling mixed timezone formats
        # datetime() normalizes ISO strings for proper sorting
        query += " ORDER BY datetime(date_sent) DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self.db.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_message(row) for row in rows]

    async def get_message(self, message_id: int) -> Message | None:
        """
        Get a single message with full body.

        Args:
            message_id: Primary key of the message.

        Returns:
            Message with body if found, None otherwise.
        """
        async with self.db.conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            message = self._row_to_message(row)

            # Also load attachments
            message.attachments = await self._get_attachments(message_id)

            return message

    async def save_message(self, message: Message) -> Message:
        """
        Save a message (insert or update).

        Args:
            message: Message to save.

        Returns:
            Saved message with ID populated.
        """
        if message.id is None:
            cursor = await self.db.conn.execute(
                """INSERT INTO messages
                   (folder_id, uid, message_id, in_reply_to, "references",
                    subject, sender, sender_name, recipients, cc, bcc,
                    date_sent, date_received, flags, spam_score,
                    body_text, body_html, raw_headers)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (message.folder_id, message.uid, message.message_id,
                 message.in_reply_to, json.dumps(message.references),
                 message.subject, message.sender, message.sender_name,
                 json.dumps(message.recipients), json.dumps(message.cc),
                 json.dumps(message.bcc),
                 message.date_sent.isoformat() if message.date_sent else None,
                 message.date_received.isoformat() if message.date_received else None,
                 int(message.flags), message.spam_score,
                 message.body_text, message.body_html, message.raw_headers)
            )
            message.id = cursor.lastrowid
        else:
            await self.db.conn.execute(
                """UPDATE messages SET
                   folder_id=?, uid=?, message_id=?, in_reply_to=?, "references"=?,
                   subject=?, sender=?, sender_name=?, recipients=?, cc=?, bcc=?,
                   date_sent=?, date_received=?, flags=?, spam_score=?,
                   body_text=?, body_html=?, raw_headers=?
                   WHERE id=?""",
                (message.folder_id, message.uid, message.message_id,
                 message.in_reply_to, json.dumps(message.references),
                 message.subject, message.sender, message.sender_name,
                 json.dumps(message.recipients), json.dumps(message.cc),
                 json.dumps(message.bcc),
                 message.date_sent.isoformat() if message.date_sent else None,
                 message.date_received.isoformat() if message.date_received else None,
                 int(message.flags), message.spam_score,
                 message.body_text, message.body_html, message.raw_headers,
                 message.id)
            )
        await self.db.conn.commit()

        # Save attachments if present
        if message.attachments and message.id:
            await self._save_attachments(message.id, message.attachments)

        return message

    async def update_message_flags(
        self,
        message_id: int,
        flags: MessageFlags,
    ) -> None:
        """
        Update just the flags on a message (efficient for read/star operations).

        Args:
            message_id: ID of the message.
            flags: New flags value.
        """
        await self.db.conn.execute(
            "UPDATE messages SET flags = ? WHERE id = ?",
            (int(flags), message_id)
        )
        await self.db.conn.commit()

    async def search_messages(
        self,
        query: str,
        *,
        account_id: int | None = None,
        folder_id: int | None = None,
        limit: int = 50,
    ) -> list[Message]:
        """
        Search messages using full-text search.

        Args:
            query: Search query (FTS5 syntax supported).
            account_id: Limit search to specific account.
            folder_id: Limit search to specific folder.
            limit: Maximum results to return.

        Returns:
            List of matching messages.
        """
        # Build the FTS query
        sql = """
            SELECT m.* FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            WHERE messages_fts MATCH ?
        """
        params: list = [query]

        if folder_id:
            sql += " AND m.folder_id = ?"
            params.append(folder_id)
        elif account_id:
            sql += " AND m.folder_id IN (SELECT id FROM folders WHERE account_id = ?)"
            params.append(account_id)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        async with self.db.conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_message(row) for row in rows]

    async def _get_attachments(self, message_id: int) -> list[Attachment]:
        """Load attachments for a message."""
        async with self.db.conn.execute(
            "SELECT * FROM attachments WHERE message_id = ?",
            (message_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_attachment(row) for row in rows]

    async def _save_attachments(
        self,
        message_id: int,
        attachments: list["Attachment"],
    ) -> None:
        """Save attachments for a message."""
        if not attachments:
            return

        # Delete existing attachments for this message first
        await self.db.conn.execute(
            "DELETE FROM attachments WHERE message_id = ?",
            (message_id,)
        )

        # Insert new attachments
        for att in attachments:
            await self.db.conn.execute(
                """INSERT INTO attachments
                   (message_id, filename, content_type, size, content_id, is_inline, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (message_id, att.filename, att.content_type, att.size,
                 att.content_id, 1 if att.is_inline else 0, att.data)
            )

        await self.db.conn.commit()

    def _row_to_message(self, row) -> Message:
        """Convert a database row to a Message object."""
        return Message(
            id=row[0],
            folder_id=row[1],
            uid=row[2],
            message_id=row[3] or "",
            in_reply_to=row[4] or "",
            references=json.loads(row[5]) if row[5] else [],
            subject=row[6] or "",
            sender=row[7] or "",
            sender_name=row[8] or "",
            recipients=json.loads(row[9]) if row[9] else [],
            cc=json.loads(row[10]) if row[10] else [],
            bcc=json.loads(row[11]) if row[11] else [],
            date_sent=datetime.fromisoformat(row[12]) if row[12] else None,
            date_received=datetime.fromisoformat(row[13]) if row[13] else None,
            flags=MessageFlags(row[14]),
            spam_score=row[15] or 0.0,
            body_text=row[16] or "",
            body_html=row[17] or "",
            raw_headers=row[18] or "",
        )

    def _row_to_attachment(self, row) -> Attachment:
        """Convert a database row to an Attachment object."""
        return Attachment(
            id=row[0],
            message_id=row[1],
            filename=row[2],
            content_type=row[3],
            size=row[4],
            content_id=row[5],
            is_inline=bool(row[6]),
            data=row[7],
        )

    # =========================================================================
    # Sync Operations
    # =========================================================================
    # These methods are specifically designed for IMAP sync operations.
    # They provide efficient bulk operations and UID-based lookups.

    async def get_message_by_uid(
        self,
        folder_id: int,
        uid: int,
    ) -> Message | None:
        """
        Get a message by its IMAP UID within a folder.

        Args:
            folder_id: Folder ID.
            uid: IMAP UID of the message.

        Returns:
            Message if found, None otherwise.
        """
        async with self.db.conn.execute(
            "SELECT * FROM messages WHERE folder_id = ? AND uid = ?",
            (folder_id, uid)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_message(row) if row else None

    async def get_highest_uid(self, folder_id: int) -> int:
        """
        Get the highest UID in a folder.

        Used for incremental sync - we only fetch messages with UID > highest.

        Args:
            folder_id: Folder ID.

        Returns:
            Highest UID, or 0 if folder is empty.
        """
        async with self.db.conn.execute(
            "SELECT MAX(uid) FROM messages WHERE folder_id = ?",
            (folder_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else 0

    async def get_local_uids(self, folder_id: int) -> set[int]:
        """
        Get all UIDs we have locally for a folder.

        Used for comparing with server to detect deletions.

        Args:
            folder_id: Folder ID.

        Returns:
            Set of UIDs stored locally.
        """
        async with self.db.conn.execute(
            "SELECT uid FROM messages WHERE folder_id = ?",
            (folder_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def get_local_flags(self, folder_id: int) -> dict[int, MessageFlags]:
        """
        Get UID -> flags mapping for a folder.

        Used for flag synchronization.

        Args:
            folder_id: Folder ID.

        Returns:
            Dictionary mapping UID to MessageFlags.
        """
        async with self.db.conn.execute(
            "SELECT uid, flags FROM messages WHERE folder_id = ?",
            (folder_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: MessageFlags(row[1]) for row in rows}

    async def delete_messages_by_uids(
        self,
        folder_id: int,
        uids: set[int],
    ) -> int:
        """
        Delete messages by their UIDs.

        Used to remove messages that were deleted on the server.

        Args:
            folder_id: Folder ID.
            uids: Set of UIDs to delete.

        Returns:
            Number of messages deleted.
        """
        if not uids:
            return 0

        # Build placeholders for IN clause
        placeholders = ",".join("?" * len(uids))
        cursor = await self.db.conn.execute(
            f"DELETE FROM messages WHERE folder_id = ? AND uid IN ({placeholders})",
            [folder_id, *uids]
        )
        await self.db.conn.commit()
        return cursor.rowcount

    async def delete_all_messages_in_folder(self, folder_id: int) -> int:
        """
        Delete all messages in a folder.

        Used when UIDVALIDITY changes and we need to re-sync everything.

        Args:
            folder_id: Folder ID.

        Returns:
            Number of messages deleted.
        """
        cursor = await self.db.conn.execute(
            "DELETE FROM messages WHERE folder_id = ?",
            (folder_id,)
        )
        await self.db.conn.commit()
        return cursor.rowcount

    async def save_messages_bulk(
        self,
        messages: list[Message],
    ) -> list[Message]:
        """
        Save multiple messages efficiently in a single transaction.

        Much faster than calling save_message() repeatedly.

        Args:
            messages: List of messages to save.

        Returns:
            List of saved messages with IDs populated.
        """
        if not messages:
            return []

        # Prepare all values
        values = []
        for msg in messages:
            values.append((
                msg.folder_id, msg.uid, msg.message_id,
                msg.in_reply_to, json.dumps(msg.references),
                msg.subject, msg.sender, msg.sender_name,
                json.dumps(msg.recipients), json.dumps(msg.cc),
                json.dumps(msg.bcc),
                msg.date_sent.isoformat() if msg.date_sent else None,
                msg.date_received.isoformat() if msg.date_received else None,
                int(msg.flags), msg.spam_score,
                msg.body_text, msg.body_html, msg.raw_headers
            ))

        # Bulk insert with INSERT OR REPLACE to handle duplicates
        await self.db.conn.executemany(
            """INSERT OR REPLACE INTO messages
               (folder_id, uid, message_id, in_reply_to, "references",
                subject, sender, sender_name, recipients, cc, bcc,
                date_sent, date_received, flags, spam_score,
                body_text, body_html, raw_headers)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values
        )
        await self.db.conn.commit()

        # Save attachments for messages that have them
        # We need to look up message IDs since executemany doesn't return them
        for msg in messages:
            if msg.attachments:
                # Get the message ID by folder_id and UID
                async with self.db.conn.execute(
                    "SELECT id FROM messages WHERE folder_id = ? AND uid = ?",
                    (msg.folder_id, msg.uid)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        msg.id = row[0]
                        await self._save_attachments(msg.id, msg.attachments)

        return messages

    async def update_flags_bulk(
        self,
        folder_id: int,
        uid_flags: dict[int, MessageFlags],
    ) -> None:
        """
        Update flags for multiple messages efficiently.

        Args:
            folder_id: Folder ID.
            uid_flags: Dictionary mapping UID to new flags.
        """
        if not uid_flags:
            return

        # Build list of updates
        updates = [(int(flags), folder_id, uid) for uid, flags in uid_flags.items()]

        await self.db.conn.executemany(
            "UPDATE messages SET flags = ? WHERE folder_id = ? AND uid = ?",
            updates
        )
        await self.db.conn.commit()

    async def get_message_count(self, folder_id: int) -> int:
        """
        Get the total number of messages in a folder.

        Args:
            folder_id: Folder ID.

        Returns:
            Total message count.
        """
        async with self.db.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE folder_id = ?",
            (folder_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_unread_count(self, folder_id: int) -> int:
        """
        Get the number of unread messages in a folder.

        Args:
            folder_id: Folder ID.

        Returns:
            Unread message count.
        """
        async with self.db.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE folder_id = ? AND (flags & ?) = 0",
            (folder_id, int(MessageFlags.SEEN))
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
