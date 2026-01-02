# =============================================================================
# IDLE Worker
# =============================================================================
# Background worker for IMAP IDLE push notifications.
#
# Key responsibilities:
#   - Maintain IDLE connections to each account's INBOX
#   - Detect new mail and notify the application
#   - Handle reconnection on errors/timeouts
#   - Graceful shutdown
#
# Design notes:
#   - Each account gets its own IDLE connection (separate from sync)
#   - IDLE ties up the connection, so we can't use it for other operations
#   - RFC recommends refreshing IDLE every 29 minutes
# =============================================================================

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Awaitable

from hawk_tui.imap.client import IMAPClient, IMAPConnectionError, IMAPAuthenticationError

if TYPE_CHECKING:
    from hawk_tui.core import Account

logger = logging.getLogger(__name__)


@dataclass
class IdleEvent:
    """Event emitted when IDLE detects changes."""
    account_id: int
    account_name: str
    folder_name: str
    event_type: str  # "new_mail", "expunge", "flags", "unknown"
    message_count: int | None = None  # For EXISTS events


# Type for the callback function
IdleCallback = Callable[[IdleEvent], Awaitable[None]]


class IdleWorker:
    """
    Background worker that monitors accounts via IMAP IDLE.

    Usage:
        >>> worker = IdleWorker()
        >>> worker.on_event = my_callback
        >>> await worker.start(accounts)
        >>> # ... later ...
        >>> await worker.stop()

    The callback receives IdleEvent objects when changes are detected.
    """

    # How long to wait before reconnecting after an error
    RECONNECT_DELAY = 30  # seconds

    # How long to keep IDLE connection before refresh (RFC recommends < 30 min)
    IDLE_TIMEOUT = 29 * 60  # 29 minutes

    def __init__(self) -> None:
        """Initialize the IDLE worker."""
        self._running = False
        self._tasks: dict[int, asyncio.Task] = {}  # account_id -> task
        self._clients: dict[int, IMAPClient] = {}  # account_id -> client
        self.on_event: IdleCallback | None = None

    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running

    async def start(self, accounts: list["Account"]) -> None:
        """
        Start IDLE monitoring for the given accounts.

        Creates a background task for each account that maintains
        an IDLE connection to the INBOX.

        Args:
            accounts: List of accounts to monitor.
        """
        if self._running:
            logger.warning("IdleWorker already running")
            return

        self._running = True
        logger.info(f"Starting IDLE worker for {len(accounts)} accounts")

        for account in accounts:
            if account.id and account.enabled:
                task = asyncio.create_task(
                    self._monitor_account(account),
                    name=f"idle-{account.name}",
                )
                self._tasks[account.id] = task

    async def stop(self) -> None:
        """
        Stop all IDLE monitoring.

        Gracefully disconnects from all accounts.
        """
        if not self._running:
            return

        logger.info("Stopping IDLE worker")
        self._running = False

        # Cancel all tasks
        for task in self._tasks.values():
            task.cancel()

        # Wait for all tasks to finish with a timeout
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks.values(), return_exceptions=True),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                logger.warning("IDLE tasks did not stop cleanly, forcing disconnect")

        # Disconnect all clients (force close)
        for account_id, client in list(self._clients.items()):
            try:
                await asyncio.wait_for(client.disconnect(), timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout disconnecting IDLE client {account_id}")
            except Exception as e:
                logger.warning(f"Error disconnecting IDLE client {account_id}: {e}")

        self._tasks.clear()
        self._clients.clear()

    async def _monitor_account(self, account: "Account") -> None:
        """
        Monitor a single account via IDLE.

        This runs in a loop, maintaining an IDLE connection and
        reconnecting on errors.
        """
        logger.info(f"Starting IDLE monitor for {account.name}")

        while self._running:
            try:
                # Create a new IMAP client for IDLE
                # (separate from the sync client)
                client = IMAPClient(account)
                self._clients[account.id] = client

                await client.connect()
                logger.debug(f"IDLE connected to {account.name}")

                # Check if server supports IDLE
                if not client.supports_idle():
                    logger.warning(f"{account.name} server does not support IDLE")
                    await client.disconnect()
                    return  # Exit this task - no point retrying

                # Enter IDLE on INBOX
                folder_name = "INBOX"
                if not await client.idle_start(folder_name):
                    logger.error(f"Failed to start IDLE on {account.name}")
                    await client.disconnect()
                    await asyncio.sleep(self.RECONNECT_DELAY)
                    continue

                # IDLE loop - wait for notifications
                while self._running:
                    try:
                        notifications = await client.idle_wait(timeout=self.IDLE_TIMEOUT)
                    except asyncio.CancelledError:
                        logger.debug(f"IDLE wait cancelled for {account.name}")
                        break

                    if not self._running:
                        break

                    # Exit IDLE to process or refresh
                    await client.idle_done()

                    if notifications:
                        # Process notifications
                        for notification in notifications:
                            event = self._parse_notification(
                                account, folder_name, notification
                            )
                            if event and self.on_event:
                                try:
                                    await self.on_event(event)
                                except Exception as e:
                                    logger.error(f"Error in IDLE callback: {e}")
                    else:
                        # Timeout - just refresh the IDLE connection
                        logger.debug(f"IDLE refresh for {account.name}")

                    # Re-enter IDLE if still running
                    if self._running:
                        if not await client.idle_start(folder_name):
                            logger.warning(f"Failed to restart IDLE on {account.name}")
                            break

                # Clean disconnect
                try:
                    await client.idle_done()
                except Exception:
                    pass
                await client.disconnect()

            except IMAPAuthenticationError as e:
                logger.error(f"IDLE auth failed for {account.name}: {e}")
                # Don't retry on auth failure - need user intervention
                return

            except IMAPConnectionError as e:
                logger.warning(f"IDLE connection lost for {account.name}: {e}")
                if self._running:
                    logger.info(f"Reconnecting IDLE for {account.name} in {self.RECONNECT_DELAY}s")
                    await asyncio.sleep(self.RECONNECT_DELAY)

            except asyncio.CancelledError:
                logger.debug(f"IDLE monitor cancelled for {account.name}")
                # Clean up before propagating
                if account.id in self._clients:
                    try:
                        await self._clients[account.id].disconnect()
                    except Exception:
                        pass
                return  # Don't re-raise, just exit cleanly

            except Exception as e:
                logger.error(f"IDLE error for {account.name}: {e}")
                if self._running:
                    await asyncio.sleep(self.RECONNECT_DELAY)

        logger.info(f"IDLE monitor stopped for {account.name}")

    def _parse_notification(
        self,
        account: "Account",
        folder_name: str,
        notification: str,
    ) -> IdleEvent | None:
        """
        Parse an IMAP IDLE notification into an event.

        Common notifications (aioimaplib strips the leading *):
            - "N EXISTS" - N messages now exist (new mail if N increased)
            - "N EXPUNGE" - Message N was deleted
            - "N FETCH (FLAGS ...)" - Flags changed on message N
        """
        notification = notification.strip()

        # aioimaplib may or may not include the leading *
        if notification.startswith("*"):
            notification = notification[1:].strip()

        # Parse EXISTS (new messages)
        match = re.match(r"(\d+)\s+EXISTS", notification, re.IGNORECASE)
        if match:
            count = int(match.group(1))
            logger.info(f"IDLE: {account.name} now has {count} messages")
            return IdleEvent(
                account_id=account.id,
                account_name=account.name,
                folder_name=folder_name,
                event_type="new_mail",
                message_count=count,
            )

        # Parse EXPUNGE (deleted)
        match = re.match(r"(\d+)\s+EXPUNGE", notification, re.IGNORECASE)
        if match:
            logger.info(f"IDLE: {account.name} message deleted")
            return IdleEvent(
                account_id=account.id,
                account_name=account.name,
                folder_name=folder_name,
                event_type="expunge",
            )

        # Parse FETCH (flag changes)
        if "FETCH" in notification.upper():
            logger.debug(f"IDLE: {account.name} flags changed")
            return IdleEvent(
                account_id=account.id,
                account_name=account.name,
                folder_name=folder_name,
                event_type="flags",
            )

        # Unknown notification
        logger.debug(f"IDLE: Unknown notification from {account.name}: {notification}")
        return None
