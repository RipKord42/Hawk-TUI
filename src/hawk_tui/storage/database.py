# =============================================================================
# Database Connection and Schema Management
# =============================================================================
# Manages SQLite database connection and schema migrations.
#
# Schema overview:
#   - accounts: Email account configurations
#   - folders: IMAP folders/mailboxes
#   - messages: Email messages with headers and bodies
#   - attachments: File attachments
#   - messages_fts: Full-text search index
#   - spam_tokens: Spam classifier training data
#
# Uses aiosqlite for async operations, with WAL mode for better
# concurrent performance.
# =============================================================================

import aiosqlite
from pathlib import Path

from hawk_tui.config import Config


# Current schema version - increment when making schema changes
SCHEMA_VERSION = 1


class Database:
    """
    Manages the SQLite database connection and schema.

    This class handles:
        - Connection pooling (single connection for now, could be expanded)
        - Schema creation and migrations
        - Enabling SQLite optimizations (WAL mode, foreign keys)

    Usage:
        >>> db = Database()
        >>> await db.connect()
        >>> async with db.connection() as conn:
        ...     await conn.execute("SELECT ...")
        >>> await db.close()

    Attributes:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """
        Initialize the database manager.

        Args:
            db_path: Path to database file. Defaults to XDG data location.
        """
        self.db_path = db_path or Config.database_path()
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """
        Open the database connection and ensure schema is up to date.

        Creates the database file if it doesn't exist.
        Runs any pending migrations.
        """
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection
        self._connection = await aiosqlite.connect(self.db_path)

        # Enable foreign keys (off by default in SQLite)
        await self._connection.execute("PRAGMA foreign_keys = ON")

        # Enable WAL mode for better concurrent performance
        await self._connection.execute("PRAGMA journal_mode = WAL")

        # Initialize or migrate schema
        await self._init_schema()

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    @property
    def conn(self) -> aiosqlite.Connection:
        """
        Get the active database connection.

        Raises:
            RuntimeError: If not connected.
        """
        if self._connection is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    async def _init_schema(self) -> None:
        """
        Initialize the database schema.

        Creates tables if they don't exist, runs migrations if needed.
        """
        # Check current schema version
        try:
            async with self.conn.execute(
                "SELECT version FROM schema_version"
            ) as cursor:
                row = await cursor.fetchone()
                current_version = row[0] if row else 0
        except aiosqlite.OperationalError:
            # Table doesn't exist, this is a fresh database
            current_version = 0

        if current_version < SCHEMA_VERSION:
            await self._create_schema()
            await self._run_migrations(current_version)

    async def _create_schema(self) -> None:
        """Create the database schema from scratch."""
        schema = """
        -- Schema version tracking
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );

        -- Email accounts
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            display_name TEXT,
            imap_host TEXT NOT NULL,
            imap_port INTEGER NOT NULL DEFAULT 993,
            imap_security TEXT NOT NULL DEFAULT 'ssl',
            smtp_host TEXT NOT NULL,
            smtp_port INTEGER NOT NULL DEFAULT 587,
            smtp_security TEXT NOT NULL DEFAULT 'starttls',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        -- IMAP folders
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            folder_type TEXT NOT NULL DEFAULT 'other',
            uidvalidity INTEGER,
            delimiter TEXT DEFAULT '/',
            total_messages INTEGER DEFAULT 0,
            unread_count INTEGER DEFAULT 0,
            last_sync TEXT,
            UNIQUE(account_id, name)
        );

        -- Email messages
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
            uid INTEGER NOT NULL,
            message_id TEXT,
            in_reply_to TEXT,
            "references" TEXT,  -- JSON array of Message-IDs
            subject TEXT,
            sender TEXT,
            sender_name TEXT,
            recipients TEXT,    -- JSON array
            cc TEXT,            -- JSON array
            bcc TEXT,           -- JSON array
            date_sent TEXT,
            date_received TEXT,
            flags INTEGER NOT NULL DEFAULT 0,
            spam_score REAL DEFAULT 0.0,
            body_text TEXT,
            body_html TEXT,
            raw_headers TEXT,
            UNIQUE(folder_id, uid)
        );

        -- Message attachments
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size INTEGER NOT NULL,
            content_id TEXT,
            is_inline INTEGER NOT NULL DEFAULT 0,
            data BLOB
        );

        -- Full-text search index for messages
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            subject,
            sender,
            sender_name,
            body_text,
            content='messages',
            content_rowid='id'
        );

        -- Triggers to keep FTS index in sync
        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, subject, sender, sender_name, body_text)
            VALUES (new.id, new.subject, new.sender, new.sender_name, new.body_text);
        END;

        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, subject, sender, sender_name, body_text)
            VALUES ('delete', old.id, old.subject, old.sender, old.sender_name, old.body_text);
        END;

        CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, subject, sender, sender_name, body_text)
            VALUES ('delete', old.id, old.subject, old.sender, old.sender_name, old.body_text);
            INSERT INTO messages_fts(rowid, subject, sender, sender_name, body_text)
            VALUES (new.id, new.subject, new.sender, new.sender_name, new.body_text);
        END;

        -- Spam classifier token frequencies
        CREATE TABLE IF NOT EXISTS spam_tokens (
            token TEXT PRIMARY KEY,
            spam_count INTEGER NOT NULL DEFAULT 0,
            ham_count INTEGER NOT NULL DEFAULT 0
        );

        -- Spam training history (which messages we've trained on)
        CREATE TABLE IF NOT EXISTS spam_training (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
            message_hash TEXT NOT NULL,  -- Hash of message for dedup
            classification TEXT NOT NULL CHECK(classification IN ('spam', 'ham')),
            trained_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(message_hash)
        );

        -- Indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_messages_folder ON messages(folder_id);
        CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date_sent DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_flags ON messages(flags);
        CREATE INDEX IF NOT EXISTS idx_folders_account ON folders(account_id);
        CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
        """

        # Execute schema creation
        await self.conn.executescript(schema)

        # Set schema version
        await self.conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,)
        )
        await self.conn.commit()

    async def _run_migrations(self, from_version: int) -> None:
        """
        Run schema migrations from the given version to current.

        Args:
            from_version: Version to migrate from.
        """
        # No migrations yet - we're at version 1
        # Future migrations would go here:
        # if from_version < 2:
        #     await self._migrate_to_v2()
        # if from_version < 3:
        #     await self._migrate_to_v3()
        pass
