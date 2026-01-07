# =============================================================================
# IMAP Sync Manager
# =============================================================================
# Manages synchronization between IMAP server and local SQLite database.
#
# Sync strategy:
#   1. Initial sync: Download all messages (or messages within max_age_days)
#   2. Incremental sync: Fetch new messages since last sync
#   3. Flag sync: Update local flags from server, push local changes
#   4. Deletion sync: Handle deleted messages
#
# Key concepts:
#   - UIDVALIDITY: If this changes, all cached UIDs are invalid
#   - HIGHESTMODSEQ: For CONDSTORE servers, enables efficient sync
#   - Full sync: Compare entire folder state (slower but always correct)
#
# Threading considerations:
#   - Sync runs in background without blocking UI
#   - Progress is reported via callbacks for UI updates
#   - Sync can be cancelled mid-operation
# =============================================================================

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable

from hawk_tui.core import Account, Folder, FolderType, Message
from hawk_tui.imap.client import IMAPClient, IMAPAuthenticationError
from hawk_tui.storage.repository import Repository
from hawk_tui.spam import SpamClassifier
from hawk_tui.config import Config


logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    """Current status of a sync operation."""
    IDLE = auto()           # Not syncing
    CONNECTING = auto()     # Connecting to server
    LISTING = auto()        # Fetching folder list
    SYNCING = auto()        # Syncing messages
    COMPLETE = auto()       # Sync completed successfully
    ERROR = auto()          # Sync failed
    CANCELLED = auto()      # Sync was cancelled


@dataclass
class SyncProgress:
    """
    Progress information for a sync operation.

    Used to update the UI with sync status.

    Attributes:
        status: Current sync status.
        account: Account being synced.
        folder: Folder currently being synced (if any).
        total_folders: Total folders to sync.
        synced_folders: Folders synced so far.
        total_messages: Total messages to sync in current folder.
        synced_messages: Messages synced so far in current folder.
        new_messages: Count of new messages fetched.
        updated_messages: Count of messages with updated flags.
        deleted_messages: Count of deleted messages.
        error: Error message if status is ERROR.
    """
    status: SyncStatus = SyncStatus.IDLE
    account: str | None = None
    folder: str | None = None
    total_folders: int = 0
    synced_folders: int = 0
    total_messages: int = 0
    synced_messages: int = 0
    new_messages: int = 0
    updated_messages: int = 0
    deleted_messages: int = 0
    error: str | None = None

    @property
    def percent_complete(self) -> float:
        """Returns completion percentage (0.0 - 100.0) for current folder."""
        if self.total_messages == 0:
            return 0.0
        return (self.synced_messages / self.total_messages) * 100.0

    @property
    def overall_percent(self) -> float:
        """Returns overall completion percentage across all folders."""
        if self.total_folders == 0:
            return 0.0
        return (self.synced_folders / self.total_folders) * 100.0


# Type alias for progress callbacks
ProgressCallback = Callable[[SyncProgress], None]


@dataclass
class SyncResult:
    """
    Result of a sync operation.

    Attributes:
        success: True if sync completed without errors.
        new_messages: Total new messages fetched.
        updated_messages: Total messages with updated flags.
        deleted_messages: Total messages removed locally.
        spam_moved: Total messages auto-moved to Junk folder.
        errors: List of error messages encountered.
        duration_seconds: Time taken for sync.
    """
    success: bool = True
    new_messages: int = 0
    updated_messages: int = 0
    deleted_messages: int = 0
    spam_moved: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class SyncManager:
    """
    Manages synchronization between IMAP server and local storage.

    The SyncManager coordinates:
        - Full sync (initial or after UIDVALIDITY change)
        - Incremental sync (new messages only)
        - Two-way flag synchronization
        - Scheduled background sync

    Usage:
        >>> sync = SyncManager(imap_client, repository, account)
        >>> result = await sync.sync_all(progress_callback=update_ui)

    Attributes:
        client: IMAP client for server communication.
        repo: Repository for local storage operations.
        account: Account being synced.
    """

    # Batch size for fetching messages (prevents memory issues)
    BATCH_SIZE = 50

    def __init__(
        self,
        client: IMAPClient,
        repo: Repository,
        account: Account,
    ) -> None:
        """
        Initialize the sync manager.

        Args:
            client: Connected IMAP client.
            repo: Storage repository for persistence.
            account: Account configuration.
        """
        self.client = client
        self.repo = repo
        self.account = account
        self._cancelled = False
        self._progress = SyncProgress()

        # Load spam classifier and config
        self._spam_classifier: SpamClassifier | None = None
        self._spam_config = self._load_spam_config()
        if self._spam_config["enabled"]:
            self._spam_classifier = SpamClassifier()
            self._spam_classifier.load()
            if self._spam_classifier.is_trained:
                logger.info(
                    f"Spam classifier loaded: {self._spam_classifier.stats.spam_count} spam, "
                    f"{self._spam_classifier.stats.ham_count} ham samples"
                )
            else:
                logger.info("Spam classifier not yet trained - auto-filtering disabled until trained")

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
        except Exception as e:
            logger.warning(f"Could not load spam config: {e}")
            return {
                "enabled": False,
                "threshold": 0.7,
                "auto_move_to_junk": False,
                "train_on_move": True,
            }

    async def _classify_and_move_spam(
        self,
        messages: list[Message],
        source_folder: Folder,
    ) -> tuple[list[Message], int]:
        """
        Classify messages and move spam to Junk folder.

        Args:
            messages: List of newly fetched messages to classify.
            source_folder: The folder messages were fetched from.

        Returns:
            Tuple of (non-spam messages to keep, count of spam moved).
        """
        # Skip if spam filtering not enabled/configured
        if not self._spam_classifier or not self._spam_classifier.is_trained:
            return messages, 0

        if not self._spam_config["auto_move_to_junk"]:
            return messages, 0

        # Don't filter messages already in Junk folder
        if source_folder.folder_type == FolderType.JUNK:
            return messages, 0

        # Don't filter Trash either
        if source_folder.folder_type == FolderType.TRASH:
            return messages, 0

        # Find the Junk folder for this account
        junk_folder = await self.repo.get_folder_by_type(
            self.account.id, FolderType.JUNK
        )
        if not junk_folder:
            logger.warning("No Junk folder found - cannot auto-move spam")
            return messages, 0

        threshold = self._spam_config["threshold"]
        spam_messages: list[Message] = []
        ham_messages: list[Message] = []

        # Classify each message
        for msg in messages:
            score = self._spam_classifier.classify(msg)
            if score >= threshold:
                logger.info(
                    f"Spam detected (score={score:.2f}): {msg.subject[:50] if msg.subject else '(no subject)'}"
                )
                spam_messages.append(msg)
                msg.mark_spam()  # Set the spam flag
            else:
                ham_messages.append(msg)

        # Move spam messages to Junk folder via IMAP
        if spam_messages:
            spam_uids = [msg.uid for msg in spam_messages if msg.uid]
            if spam_uids:
                try:
                    await self.client.move_messages(
                        source_folder.name,
                        junk_folder.name,
                        spam_uids,
                    )
                    logger.info(
                        f"Moved {len(spam_uids)} spam messages to {junk_folder.name}"
                    )

                    # Update folder_id for moved messages so they're saved correctly
                    for msg in spam_messages:
                        msg.folder_id = junk_folder.id

                except Exception as e:
                    logger.error(f"Failed to move spam to Junk: {e}")
                    # On failure, keep messages in original folder
                    ham_messages.extend(spam_messages)
                    return ham_messages, 0

        return ham_messages, len(spam_messages)

    def _report_progress(
        self,
        callback: ProgressCallback | None,
        **updates,
    ) -> None:
        """
        Update progress and notify callback.

        Args:
            callback: Optional callback to notify.
            **updates: Fields to update in progress.
        """
        for key, value in updates.items():
            if hasattr(self._progress, key):
                setattr(self._progress, key, value)

        if callback:
            callback(self._progress)

    async def sync_all(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        sync_flags: bool = True,
        sync_deletions: bool = True,
    ) -> SyncResult:
        """
        Perform a full sync of all folders.

        This is the main entry point for synchronization.

        Args:
            progress_callback: Function to call with progress updates.
            sync_flags: If True, sync message flags bidirectionally.
            sync_deletions: If True, delete local messages removed on server.

        Returns:
            SyncResult indicating success/failure and statistics.
        """
        start_time = datetime.now()
        result = SyncResult()
        self._cancelled = False
        self._progress = SyncProgress(
            status=SyncStatus.CONNECTING,
            account=self.account.name,
        )

        try:
            # Ensure we're connected
            self._report_progress(progress_callback, status=SyncStatus.CONNECTING)

            if not self.client.is_connected:
                await self.client.connect()

            logger.info(f"Starting sync for account: {self.account.name}")

            # Ensure account exists in database
            db_account = await self.repo.get_account_by_name(self.account.name)
            if not db_account:
                # Save account to database
                self.account.id = None  # Clear to force insert
                db_account = await self.repo.save_account(self.account)
                self.account.id = db_account.id
            else:
                self.account.id = db_account.id

            # Fetch and sync folder list
            self._report_progress(progress_callback, status=SyncStatus.LISTING)
            server_folders = await self.client.list_folders()
            logger.info(f"Found {len(server_folders)} folders on server")

            # Sync folder metadata to database
            await self._sync_folders(server_folders)

            # Get folders to sync
            db_folders = await self.repo.get_folders(self.account.id)
            self._report_progress(
                progress_callback,
                status=SyncStatus.SYNCING,
                total_folders=len(db_folders),
            )

            # Sync each folder
            for i, folder in enumerate(db_folders):
                if self._cancelled:
                    self._report_progress(progress_callback, status=SyncStatus.CANCELLED)
                    result.success = False
                    break

                self._report_progress(
                    progress_callback,
                    folder=folder.name,
                    synced_folders=i,
                    total_messages=0,
                    synced_messages=0,
                )

                try:
                    folder_result = await self.sync_folder(
                        folder,
                        progress_callback=progress_callback,
                        sync_flags=sync_flags,
                        sync_deletions=sync_deletions,
                    )

                    result.new_messages += folder_result.new_messages
                    result.updated_messages += folder_result.updated_messages
                    result.deleted_messages += folder_result.deleted_messages
                    result.spam_moved += folder_result.spam_moved
                    result.errors.extend(folder_result.errors)

                except Exception as e:
                    error_msg = f"Error syncing {folder.name}: {e}"
                    logger.error(error_msg, exc_info=True)
                    result.errors.append(error_msg)

            # Final progress update
            if result.success and not self._cancelled:
                self._report_progress(
                    progress_callback,
                    status=SyncStatus.COMPLETE,
                    synced_folders=len(db_folders),
                )
                logger.info(
                    f"Sync complete: {result.new_messages} new, "
                    f"{result.updated_messages} updated, "
                    f"{result.deleted_messages} deleted"
                )
            else:
                result.success = False

        except IMAPAuthenticationError:
            # Re-raise authentication errors so UI can prompt for password
            raise
        except Exception as e:
            error_msg = f"Sync failed: {e}"
            logger.error(error_msg, exc_info=True)
            result.success = False
            result.errors.append(error_msg)
            self._report_progress(
                progress_callback,
                status=SyncStatus.ERROR,
                error=error_msg,
            )

        result.duration_seconds = (datetime.now() - start_time).total_seconds()
        return result

    async def _sync_folders(self, server_folders: list[Folder]) -> None:
        """
        Sync folder metadata from server to local database.

        Creates new folders, updates existing ones, removes deleted ones.

        Args:
            server_folders: List of folders from the IMAP server.
        """
        # Get current local folders
        local_folders = await self.repo.get_folders(self.account.id)
        local_by_name = {f.name: f for f in local_folders}
        server_names = {f.name for f in server_folders}

        # Update or create folders
        for server_folder in server_folders:
            local_folder = local_by_name.get(server_folder.name)

            if local_folder:
                # Update existing folder
                local_folder.folder_type = server_folder.folder_type
                local_folder.delimiter = server_folder.delimiter
                local_folder.total_messages = server_folder.total_messages
                local_folder.unread_count = server_folder.unread_count
                # Don't update uidvalidity here - that's checked during message sync
                await self.repo.save_folder(local_folder)
            else:
                # Create new folder
                server_folder.account_id = self.account.id
                await self.repo.save_folder(server_folder)

        # Remove folders that no longer exist on server
        for local_folder in local_folders:
            if local_folder.name not in server_names:
                logger.info(f"Removing deleted folder: {local_folder.name}")
                await self.repo.delete_folder(local_folder.id)

    async def sync_folder(
        self,
        folder: Folder,
        *,
        progress_callback: ProgressCallback | None = None,
        sync_flags: bool = True,
        sync_deletions: bool = True,
    ) -> SyncResult:
        """
        Sync a single folder.

        Args:
            folder: Folder to sync.
            progress_callback: Function to call with progress updates.
            sync_flags: If True, sync message flags.
            sync_deletions: If True, delete local messages removed on server.

        Returns:
            SyncResult for this folder.
        """
        result = SyncResult()

        if self._cancelled:
            return result

        logger.debug(f"Syncing folder: {folder.name}")

        try:
            # Select folder and get current status
            status = await self.client.select_folder(folder.name)
            server_uidvalidity = status.get("UIDVALIDITY")
            server_exists = status.get("EXISTS", 0)

            self._report_progress(
                progress_callback,
                total_messages=server_exists,
            )

            # Check UIDVALIDITY
            uidvalidity_changed = await self._check_uidvalidity(
                folder, server_uidvalidity
            )

            if uidvalidity_changed:
                # UIDVALIDITY changed - need full resync
                logger.warning(
                    f"UIDVALIDITY changed for {folder.name}: "
                    f"{folder.uidvalidity} -> {server_uidvalidity}"
                )
                result = await self._full_folder_sync(
                    folder,
                    server_uidvalidity,
                    progress_callback=progress_callback,
                )
            else:
                # Incremental sync
                result = await self._incremental_sync(
                    folder,
                    progress_callback=progress_callback,
                )

            # Sync flags if requested
            if sync_flags and not self._cancelled:
                flags_result = await self._sync_flags(folder)
                result.updated_messages += flags_result

            # Sync deletions if requested
            if sync_deletions and not self._cancelled:
                deleted = await self._sync_deletions(folder)
                result.deleted_messages += deleted

            # Update folder metadata
            folder.total_messages = await self.repo.get_message_count(folder.id)
            folder.unread_count = await self.repo.get_unread_count(folder.id)
            folder.last_sync = datetime.now()
            folder.uidvalidity = server_uidvalidity
            await self.repo.save_folder(folder)

        except Exception as e:
            error_msg = f"Error syncing folder {folder.name}: {e}"
            logger.error(error_msg, exc_info=True)
            result.success = False
            result.errors.append(error_msg)

        return result

    async def _check_uidvalidity(
        self,
        folder: Folder,
        server_uidvalidity: int | None,
    ) -> bool:
        """
        Check if folder's UIDVALIDITY has changed.

        If UIDVALIDITY changed, we need to re-sync the entire folder
        because all our cached UIDs are invalid.

        Args:
            folder: Folder to check.
            server_uidvalidity: Current UIDVALIDITY from server.

        Returns:
            True if UIDVALIDITY changed (need full sync), False otherwise.
        """
        if folder.uidvalidity is None:
            # First sync of this folder
            return True

        if server_uidvalidity is None:
            # Server didn't provide UIDVALIDITY (unusual)
            logger.warning(f"Server didn't provide UIDVALIDITY for {folder.name}")
            return False

        return folder.uidvalidity != server_uidvalidity

    async def _full_folder_sync(
        self,
        folder: Folder,
        server_uidvalidity: int | None,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> SyncResult:
        """
        Perform a full sync of a folder (download all messages).

        Used for initial sync or after UIDVALIDITY change.
        Fetches messages in batches to show progress and avoid timeouts.

        Args:
            folder: Folder to sync.
            server_uidvalidity: New UIDVALIDITY value.
            progress_callback: Progress callback.

        Returns:
            SyncResult with statistics.
        """
        result = SyncResult()

        logger.info(f"Full sync of {folder.name}")

        # Clear all existing messages (UIDVALIDITY changed means UIDs are invalid)
        deleted = await self.repo.delete_all_messages_in_folder(folder.id)
        logger.debug(f"Cleared {deleted} existing messages from {folder.name}")

        # Get all UIDs from server
        all_uids = sorted(await self.client.get_folder_uids(folder.name))
        total_messages = len(all_uids)

        if total_messages == 0:
            logger.info(f"Full sync of {folder.name} complete: 0 messages")
            folder.uidvalidity = server_uidvalidity
            return result

        logger.debug(f"Full sync {folder.name}: {total_messages} messages to fetch")

        # Fetch messages in batches
        fetched_count = 0
        for i in range(0, total_messages, self.BATCH_SIZE):
            if self._cancelled:
                break

            batch_uids = all_uids[i:i + self.BATCH_SIZE]
            batch_num = (i // self.BATCH_SIZE) + 1
            total_batches = (total_messages + self.BATCH_SIZE - 1) // self.BATCH_SIZE

            logger.debug(
                f"Fetching batch {batch_num}/{total_batches} "
                f"({len(batch_uids)} messages) from {folder.name}"
            )

            # Report progress before fetching
            self._report_progress(
                progress_callback,
                folder=f"{folder.name} ({fetched_count}/{total_messages})",
            )

            messages = await self.client.fetch_messages(
                folder.name,
                uids=batch_uids,
                fetch_body=True,
            )

            if messages:
                # Prepare messages for storage
                for msg in messages:
                    msg.folder_id = folder.id

                # Classify and move spam (before saving to database)
                ham_messages, spam_count = await self._classify_and_move_spam(
                    messages, folder
                )
                result.spam_moved += spam_count

                # Save messages to database
                await self.repo.save_messages_bulk(ham_messages)

                fetched_count += len(messages)
                result.new_messages += len(messages)

                self._report_progress(
                    progress_callback,
                    synced_messages=fetched_count,
                    new_messages=self._progress.new_messages + fetched_count,
                    folder=f"{folder.name} ({fetched_count}/{total_messages})",
                )

        # Update folder's UIDVALIDITY
        folder.uidvalidity = server_uidvalidity

        if result.spam_moved > 0:
            logger.info(
                f"Full sync of {folder.name} complete: {result.new_messages} messages "
                f"({result.spam_moved} moved to Junk)"
            )
        else:
            logger.info(f"Full sync of {folder.name} complete: {result.new_messages} messages")
        return result

    async def _incremental_sync(
        self,
        folder: Folder,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> SyncResult:
        """
        Perform an incremental sync (new messages only).

        Compares server UIDs with local UIDs to detect:
        1. New messages (UIDs we don't have)
        2. Messages moved in from other clients (may have lower UIDs)

        Fetches missing messages in batches to avoid timeouts and show progress.

        Args:
            folder: Folder to sync.
            progress_callback: Progress callback.

        Returns:
            SyncResult with statistics.
        """
        result = SyncResult()

        # Get all UIDs from server and locally
        server_uids = await self.client.get_folder_uids(folder.name)
        local_uids = await self.repo.get_local_uids(folder.id)

        # Find UIDs on server that we don't have locally
        missing_uids = sorted(server_uids - local_uids)  # Sort for consistent ordering
        total_missing = len(missing_uids)

        logger.debug(
            f"Incremental sync {folder.name}: "
            f"server={len(server_uids)}, local={len(local_uids)}, missing={total_missing}"
        )

        if not missing_uids:
            logger.debug(f"Incremental sync {folder.name}: no new messages")
            return result

        # Fetch missing messages in batches
        fetched_count = 0
        for i in range(0, total_missing, self.BATCH_SIZE):
            if self._cancelled:
                break

            batch_uids = missing_uids[i:i + self.BATCH_SIZE]
            batch_num = (i // self.BATCH_SIZE) + 1
            total_batches = (total_missing + self.BATCH_SIZE - 1) // self.BATCH_SIZE

            logger.debug(
                f"Fetching batch {batch_num}/{total_batches} "
                f"({len(batch_uids)} messages) from {folder.name}"
            )

            # Report progress before fetching
            self._report_progress(
                progress_callback,
                folder=f"{folder.name} ({fetched_count}/{total_missing})",
            )

            messages = await self.client.fetch_messages(
                folder.name,
                uids=batch_uids,
                fetch_body=True,
            )

            if messages:
                # Prepare messages for storage
                for msg in messages:
                    msg.folder_id = folder.id

                # Classify and move spam (before saving to database)
                ham_messages, spam_count = await self._classify_and_move_spam(
                    messages, folder
                )
                result.spam_moved += spam_count

                # Debug: Log if there's a mismatch between fetched and saved
                if len(ham_messages) + spam_count != len(messages):
                    logger.warning(
                        f"Message count mismatch in {folder.name}: "
                        f"fetched={len(messages)}, ham={len(ham_messages)}, spam={spam_count}"
                    )

                # Save messages to database
                if ham_messages:
                    await self.repo.save_messages_bulk(ham_messages)
                    logger.debug(f"Saved {len(ham_messages)} messages to {folder.name}")

                fetched_count += len(messages)
                result.new_messages += len(messages)

                self._report_progress(
                    progress_callback,
                    synced_messages=fetched_count,
                    new_messages=self._progress.new_messages + fetched_count,
                    folder=f"{folder.name} ({fetched_count}/{total_missing})",
                )

        if result.spam_moved > 0:
            logger.info(
                f"Incremental sync {folder.name}: {result.new_messages} new messages "
                f"({result.spam_moved} moved to Junk)"
            )
        else:
            logger.info(f"Incremental sync {folder.name}: {result.new_messages} new messages")

        return result

    async def _sync_flags(self, folder: Folder) -> int:
        """
        Synchronize message flags between server and local.

        Currently this is one-way: server -> local.
        TODO: Implement bidirectional sync for local flag changes.

        Args:
            folder: Folder to sync flags for.

        Returns:
            Number of messages with updated flags.
        """
        updated_count = 0

        # Get local UID -> flags mapping
        local_flags = await self.repo.get_local_flags(folder.id)

        if not local_flags:
            return 0

        # Fetch current flags from server for these UIDs
        uids = list(local_flags.keys())

        # Fetch flags in batches to avoid huge responses
        updates: dict[int, any] = {}
        for i in range(0, len(uids), self.BATCH_SIZE):
            batch_uids = uids[i:i + self.BATCH_SIZE]
            server_messages = await self.client.fetch_messages(
                folder.name,
                uids=batch_uids,
            )

            # Compare and collect updates
            for msg in server_messages:
                local_msg_flags = local_flags.get(msg.uid)
                if local_msg_flags is not None and local_msg_flags != msg.flags:
                    updates[msg.uid] = msg.flags

        # Apply flag updates
        if updates:
            await self.repo.update_flags_bulk(folder.id, updates)
            updated_count = len(updates)
            logger.debug(f"Updated flags for {updated_count} messages in {folder.name}")

        return updated_count

    async def _sync_deletions(self, folder: Folder) -> int:
        """
        Remove locally cached messages that were deleted on server.

        Args:
            folder: Folder to check for deletions.

        Returns:
            Number of messages deleted locally.
        """
        # Get local UIDs
        local_uids = await self.repo.get_local_uids(folder.id)

        if not local_uids:
            return 0

        # Get server UIDs - we need to fetch just the UIDs
        # For efficiency, we could use IMAP SEARCH UID ALL
        # For now, we'll fetch minimal data
        server_messages = await self.client.fetch_messages(
            folder.name,
            uids=list(local_uids),
        )
        server_uids = {msg.uid for msg in server_messages}

        # Find UIDs that exist locally but not on server
        deleted_uids = local_uids - server_uids

        if deleted_uids:
            deleted_count = await self.repo.delete_messages_by_uids(
                folder.id, deleted_uids
            )
            logger.info(
                f"Deleted {deleted_count} messages from {folder.name} "
                f"(removed from server)"
            )
            return deleted_count

        return 0

    def cancel(self) -> None:
        """
        Request cancellation of the current sync operation.

        The sync will stop at the next safe point.
        """
        logger.info("Sync cancellation requested")
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if sync was cancelled."""
        return self._cancelled
