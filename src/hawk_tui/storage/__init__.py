# =============================================================================
# Storage Module
# =============================================================================
# Handles persistent storage using SQLite.
#
# Provides:
#   - Database initialization and migrations
#   - CRUD operations for accounts, folders, messages
#   - Full-text search via SQLite FTS5
#   - Async operations via aiosqlite
#
# All email data is stored locally for offline access. The database
# is stored in the XDG data directory (~/.local/share/hawk-tui/).
# =============================================================================

from hawk_tui.storage.database import Database
from hawk_tui.storage.repository import Repository

__all__ = ["Database", "Repository"]
