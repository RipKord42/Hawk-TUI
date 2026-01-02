# =============================================================================
# Folder Tree Widget
# =============================================================================
# A hierarchical tree view of email folders.
#
# Features:
#   - Collapsible nested folders
#   - Unread counts
#   - Icons for special folders (Inbox, Sent, Trash, etc.)
#   - Multiple account support
# =============================================================================

from textual.widgets import Tree
from textual.widgets.tree import TreeNode
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawk_tui.core import Account, Folder


class FolderTree(Tree):
    """
    A tree widget displaying email folders.

    Shows a hierarchical view of all folders across all accounts,
    with unread counts and special folder icons.

    Usage:
        >>> tree = FolderTree("Mailboxes")
        >>> await tree.load_accounts(accounts, folders)
    """

    # Icons for special folder types
    # Note: Avoid emojis with variation selectors (️) as they cause terminal width issues
    FOLDER_ICONS = {
        "inbox": "📥",
        "sent": "📤",
        "drafts": "📝",
        "trash": "🗑",
        "junk": "⛔",
        "archive": "📦",
        "other": "📁",
    }

    def __init__(self, label: str = "Mailboxes", **kwargs) -> None:
        """
        Initialize the folder tree.

        Args:
            label: Root node label.
            **kwargs: Additional arguments passed to Tree.
        """
        super().__init__(label, **kwargs)
        self._folders: dict[int, "Folder"] = {}  # folder_id -> Folder

    async def load_accounts(
        self,
        accounts: list["Account"],
        folders_by_account: dict[int, list["Folder"]],
    ) -> None:
        """
        Load accounts and folders into the tree.

        Args:
            accounts: List of email accounts.
            folders_by_account: Dictionary mapping account_id to list of folders.
        """
        self.clear()

        for account in accounts:
            if not account.enabled:
                continue

            # Add account node
            account_node = self.root.add(
                f"📧 {account.name}",
                data={"type": "account", "id": account.id},
            )

            # Add folders for this account
            folders = folders_by_account.get(account.id, [])
            await self._add_folders(account_node, folders)

            # Expand account node to show folders
            account_node.expand()

        # Expand root to show everything
        self.root.expand()

        # Force refresh to update display
        self.refresh()

    async def _add_folders(
        self,
        parent_node: TreeNode,
        folders: list["Folder"],
    ) -> None:
        """
        Add folders to a tree node.

        Handles nested folders by parsing the delimiter recursively.
        """
        # Build a tree structure from folder paths
        # Group folders by their immediate parent
        children_by_parent: dict[str, list["Folder"]] = {}
        root_folders: list["Folder"] = []

        for folder in folders:
            if folder.delimiter and folder.delimiter in folder.name:
                parent_path = folder.name.rsplit(folder.delimiter, 1)[0]
                if parent_path not in children_by_parent:
                    children_by_parent[parent_path] = []
                children_by_parent[parent_path].append(folder)
            else:
                root_folders.append(folder)

        # Sort folders (special folders first, then alphabetically)
        def folder_sort_key(f: "Folder") -> tuple[int, str]:
            order = {"inbox": 0, "sent": 1, "drafts": 2, "trash": 3, "junk": 4, "archive": 5}
            return (order.get(f.folder_type.name.lower(), 99), f.name.lower())

        root_folders.sort(key=folder_sort_key)

        # Recursively add folders
        def add_folder_recursive(parent: TreeNode, folder: "Folder") -> None:
            label = self._folder_label(folder)
            node = parent.add(
                label,
                data={"type": "folder", "id": folder.id},
            )

            # Store reference
            if folder.id:
                self._folders[folder.id] = folder

            # Add children recursively if any
            if folder.name in children_by_parent:
                children = sorted(children_by_parent[folder.name], key=folder_sort_key)
                for child in children:
                    add_folder_recursive(node, child)
                # Expand parent folders that have children
                node.expand()

        # Add all root folders
        for folder in root_folders:
            add_folder_recursive(parent_node, folder)

    def _folder_label(self, folder: "Folder") -> str:
        """
        Create a display label for a folder.

        Includes icon and unread count.
        """
        icon = self.FOLDER_ICONS.get(folder.folder_type.name.lower(), "📁")
        name = folder.display_name

        if folder.unread_count > 0:
            return f"{icon} {name} ({folder.unread_count})"
        return f"{icon} {name}"

    def get_selected_folder(self) -> "Folder | None":
        """
        Get the currently selected folder.

        Returns:
            Selected Folder or None if no folder is selected.
        """
        node = self.cursor_node
        if node and node.data and node.data.get("type") == "folder":
            folder_id = node.data.get("id")
            return self._folders.get(folder_id)
        return None

    def update_unread_count(self, folder_id: int, count: int) -> None:
        """
        Update the unread count display for a folder.

        Args:
            folder_id: ID of the folder to update.
            count: New unread count.
        """
        if folder_id in self._folders:
            self._folders[folder_id].unread_count = count
            # TODO: Update tree node label
