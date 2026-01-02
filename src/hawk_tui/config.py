# =============================================================================
# Configuration Management
# =============================================================================
# Handles loading, saving, and validating Hawk-TUI configuration.
#
# XDG Base Directory Compliance (https://specifications.freedesktop.org/basedir-spec/):
#   - Config:  $XDG_CONFIG_HOME/hawk-tui/  (default: ~/.config/hawk-tui/)
#   - Data:    $XDG_DATA_HOME/hawk-tui/    (default: ~/.local/share/hawk-tui/)
#   - Cache:   $XDG_CACHE_HOME/hawk-tui/   (default: ~/.cache/hawk-tui/)
#   - State:   $XDG_STATE_HOME/hawk-tui/   (default: ~/.local/state/hawk-tui/)
#
# Files:
#   - config.toml: User configuration (accounts, preferences)
#   - hawk-tui.db: SQLite database (in data directory)
#   - rendered/: Cached rendered content (in cache directory)
#   - sync_state.json: Synchronization state (in state directory)
# =============================================================================

import os
import tomllib  # Built into Python 3.11+
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w  # For writing TOML (tomllib is read-only)

from hawk_tui.core import Account


# =============================================================================
# XDG Directory Management
# =============================================================================

# Application identifier used in all XDG paths
APP_NAME = "hawk-tui"


def get_xdg_config_home() -> Path:
    """
    Returns the XDG config directory for Hawk-TUI.

    Respects $XDG_CONFIG_HOME if set, otherwise uses ~/.config/hawk-tui/
    This is where user configuration files live (config.toml).
    """
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"
    return base / APP_NAME


def get_xdg_data_home() -> Path:
    """
    Returns the XDG data directory for Hawk-TUI.

    Respects $XDG_DATA_HOME if set, otherwise uses ~/.local/share/hawk-tui/
    This is where persistent data lives (SQLite database, spam training data).
    """
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        base = Path(xdg_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / APP_NAME


def get_xdg_cache_home() -> Path:
    """
    Returns the XDG cache directory for Hawk-TUI.

    Respects $XDG_CACHE_HOME if set, otherwise uses ~/.cache/hawk-tui/
    This is where cached data lives (rendered images, temporary files).
    Cache can be safely deleted without data loss.
    """
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache)
    else:
        base = Path.home() / ".cache"
    return base / APP_NAME


def get_xdg_state_home() -> Path:
    """
    Returns the XDG state directory for Hawk-TUI.

    Respects $XDG_STATE_HOME if set, otherwise uses ~/.local/state/hawk-tui/
    This is where state data lives (sync state, window positions).
    State is like cache but shouldn't be shared across machines.
    """
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        base = Path(xdg_state)
    else:
        base = Path.home() / ".local" / "state"
    return base / APP_NAME


def ensure_directories() -> dict[str, Path]:
    """
    Creates all required XDG directories if they don't exist.

    Returns:
        Dictionary mapping directory type to path.

    Example:
        >>> dirs = ensure_directories()
        >>> dirs['config']
        PosixPath('/home/user/.config/hawk-tui')
    """
    dirs = {
        "config": get_xdg_config_home(),
        "data": get_xdg_data_home(),
        "cache": get_xdg_cache_home(),
        "state": get_xdg_state_home(),
    }

    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)

    # Also create subdirectories we know we'll need
    (dirs["cache"] / "rendered").mkdir(exist_ok=True)  # For cached rendered HTML

    return dirs


# =============================================================================
# Configuration Data Structures
# =============================================================================

@dataclass
class RenderingConfig:
    """
    Configuration for the HTML rendering engine.

    Attributes:
        mode: Rendering mode selection.
              - "fast": Always use inscriptis (text-based rendering)
              - "browser": Always use headless browser (perfect but slow)
              - "auto": Try fast first, fall back to browser for complex emails
        image_protocol: Terminal graphics protocol to use.
                        - "sixel": Widely supported, older protocol
                        - "kitty": Better quality, requires Kitty terminal
                        - "auto": Auto-detect terminal capabilities
        max_image_width: Maximum width for inline images (in terminal cells).
        max_image_height: Maximum height for inline images (in terminal cells).
    """
    mode: str = "auto"                  # "fast", "browser", or "auto"
    image_protocol: str = "auto"        # "sixel", "kitty", or "auto"
    max_image_width: int = 80           # Max image width in terminal columns
    max_image_height: int = 40          # Max image height in terminal rows


@dataclass
class SpamConfig:
    """
    Configuration for the spam filter.

    Attributes:
        enabled: Whether spam filtering is active.
        threshold: Score threshold for classifying as spam (0.0-1.0).
                   Messages with score >= threshold are marked as spam.
        auto_move_to_junk: Automatically move spam to Junk folder on server.
        train_on_move: Train the classifier when user manually moves messages
                       to/from Junk folder.
    """
    enabled: bool = True
    threshold: float = 0.7              # Scores >= this are spam
    auto_move_to_junk: bool = True      # Auto-move to Junk folder
    train_on_move: bool = True          # Learn from user's junk/not-junk actions


@dataclass
class SyncConfig:
    """
    Configuration for email synchronization.

    Attributes:
        check_interval_minutes: How often to check for new mail (0 = manual only).
        use_idle: Use IMAP IDLE for push notifications (if server supports it).
        sync_deleted: Sync deleted messages (some people want to keep everything).
        max_age_days: Only sync messages newer than this (0 = all messages).
                      Useful for large mailboxes where you don't need old mail.
    """
    check_interval_minutes: int = 5
    use_idle: bool = True               # Use IMAP IDLE for push
    sync_deleted: bool = False          # Sync messages marked as deleted
    max_age_days: int = 0               # 0 = sync all, >0 = only recent


@dataclass
class UIConfig:
    """
    Configuration for the user interface.

    Attributes:
        theme: Color theme ("dark" or "light").
        date_format: Format string for displaying dates (strftime format).
        time_format: Format string for displaying times.
        confirm_delete: Require confirmation before deleting messages.
        preview_lines: Number of lines to show in message preview.
    """
    theme: str = "dark"
    date_format: str = "%Y-%m-%d"
    time_format: str = "%H:%M"
    confirm_delete: bool = True
    preview_lines: int = 2


@dataclass
class Config:
    """
    Main configuration container for Hawk-TUI.

    This is the top-level configuration object that holds all settings
    and account information.

    Attributes:
        default_account: Name of the account to select on startup.
        accounts: Dictionary of configured email accounts, keyed by name.
        rendering: HTML rendering configuration.
        spam: Spam filter configuration.
        sync: Synchronization configuration.
        ui: User interface configuration.

    Usage:
        >>> config = Config.load()
        >>> print(config.accounts['personal'].email)
        'user@example.com'
    """
    # General settings
    default_account: str = ""

    # Account configurations (name -> Account)
    accounts: dict[str, Account] = field(default_factory=dict)

    # Subsystem configurations
    rendering: RenderingConfig = field(default_factory=RenderingConfig)
    spam: SpamConfig = field(default_factory=SpamConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    # -------------------------------------------------------------------------
    # File Paths
    # -------------------------------------------------------------------------

    @staticmethod
    def config_file_path() -> Path:
        """Returns the path to the main config file."""
        return get_xdg_config_home() / "config.toml"

    @staticmethod
    def database_path() -> Path:
        """Returns the path to the SQLite database."""
        return get_xdg_data_home() / "hawk-tui.db"

    @staticmethod
    def spam_model_path() -> Path:
        """Returns the path to the spam classifier model."""
        return get_xdg_data_home() / "spam_model.json"

    @staticmethod
    def cache_dir() -> Path:
        """Returns the cache directory path."""
        return get_xdg_cache_home()

    @staticmethod
    def state_dir() -> Path:
        """Returns the state directory path."""
        return get_xdg_state_home()

    # -------------------------------------------------------------------------
    # Loading and Saving
    # -------------------------------------------------------------------------

    @classmethod
    def load(cls) -> "Config":
        """
        Load configuration from the config file.

        If the config file doesn't exist, returns default configuration.
        Creates necessary directories if they don't exist.

        Returns:
            Loaded Config object.

        Raises:
            ConfigError: If the config file exists but is invalid.
        """
        # Ensure all XDG directories exist
        ensure_directories()

        config_path = cls.config_file_path()

        if not config_path.exists():
            # No config file yet - return defaults
            return cls()

        # Load and parse the TOML file
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid config file: {e}") from e

        return cls._from_dict(data)

    def save(self) -> None:
        """
        Save configuration to the config file.

        Creates the config directory if it doesn't exist.
        """
        ensure_directories()

        config_path = self.config_file_path()
        data = self._to_dict()

        with open(config_path, "wb") as f:
            tomli_w.dump(data, f)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "Config":
        """
        Create a Config object from a dictionary (parsed TOML).

        This handles the nested structure of the config file and
        converts account entries into Account objects.
        """
        config = cls()

        # General settings
        general = data.get("general", {})
        config.default_account = general.get("default_account", "")

        # Rendering settings
        rendering = data.get("rendering", {})
        config.rendering = RenderingConfig(
            mode=rendering.get("mode", "auto"),
            image_protocol=rendering.get("image_protocol", "auto"),
            max_image_width=rendering.get("max_image_width", 80),
            max_image_height=rendering.get("max_image_height", 40),
        )

        # Spam settings
        spam = data.get("spam", {})
        config.spam = SpamConfig(
            enabled=spam.get("enabled", True),
            threshold=spam.get("threshold", 0.7),
            auto_move_to_junk=spam.get("auto_move_to_junk", True),
            train_on_move=spam.get("train_on_move", True),
        )

        # Sync settings
        sync = data.get("sync", {})
        config.sync = SyncConfig(
            check_interval_minutes=sync.get("check_interval_minutes", 5),
            use_idle=sync.get("use_idle", True),
            sync_deleted=sync.get("sync_deleted", False),
            max_age_days=sync.get("max_age_days", 0),
        )

        # UI settings
        ui = data.get("ui", {})
        config.ui = UIConfig(
            theme=ui.get("theme", "dark"),
            date_format=ui.get("date_format", "%Y-%m-%d"),
            time_format=ui.get("time_format", "%H:%M"),
            confirm_delete=ui.get("confirm_delete", True),
            preview_lines=ui.get("preview_lines", 2),
        )

        # Accounts - each key under [accounts] is an account name
        accounts_data = data.get("accounts", {})
        for name, acct_data in accounts_data.items():
            config.accounts[name] = Account(
                name=name,
                email=acct_data.get("email", ""),
                display_name=acct_data.get("display_name", ""),
                imap_host=acct_data.get("imap_host", ""),
                imap_port=acct_data.get("imap_port", 993),
                imap_security=acct_data.get("imap_security", "ssl"),
                smtp_host=acct_data.get("smtp_host", ""),
                smtp_port=acct_data.get("smtp_port", 587),
                smtp_security=acct_data.get("smtp_security", "starttls"),
                enabled=acct_data.get("enabled", True),
            )

        return config

    def _to_dict(self) -> dict[str, Any]:
        """
        Convert Config to a dictionary for TOML serialization.
        """
        data: dict[str, Any] = {}

        # General settings
        data["general"] = {
            "default_account": self.default_account,
        }

        # Rendering settings
        data["rendering"] = {
            "mode": self.rendering.mode,
            "image_protocol": self.rendering.image_protocol,
            "max_image_width": self.rendering.max_image_width,
            "max_image_height": self.rendering.max_image_height,
        }

        # Spam settings
        data["spam"] = {
            "enabled": self.spam.enabled,
            "threshold": self.spam.threshold,
            "auto_move_to_junk": self.spam.auto_move_to_junk,
            "train_on_move": self.spam.train_on_move,
        }

        # Sync settings
        data["sync"] = {
            "check_interval_minutes": self.sync.check_interval_minutes,
            "use_idle": self.sync.use_idle,
            "sync_deleted": self.sync.sync_deleted,
            "max_age_days": self.sync.max_age_days,
        }

        # UI settings
        data["ui"] = {
            "theme": self.ui.theme,
            "date_format": self.ui.date_format,
            "time_format": self.ui.time_format,
            "confirm_delete": self.ui.confirm_delete,
            "preview_lines": self.ui.preview_lines,
        }

        # Accounts
        data["accounts"] = {}
        for name, account in self.accounts.items():
            data["accounts"][name] = {
                "email": account.email,
                "display_name": account.display_name,
                "imap_host": account.imap_host,
                "imap_port": account.imap_port,
                "imap_security": account.imap_security,
                "smtp_host": account.smtp_host,
                "smtp_port": account.smtp_port,
                "smtp_security": account.smtp_security,
                "enabled": account.enabled,
            }

        return data


# =============================================================================
# Exceptions
# =============================================================================

class ConfigError(Exception):
    """Raised when there's an error loading or parsing configuration."""
    pass


# =============================================================================
# Utility Functions
# =============================================================================

def print_paths() -> None:
    """
    Print all XDG paths for debugging.
    Useful for users wondering where their config/data is stored.
    """
    print(f"Config:  {get_xdg_config_home()}")
    print(f"Data:    {get_xdg_data_home()}")
    print(f"Cache:   {get_xdg_cache_home()}")
    print(f"State:   {get_xdg_state_home()}")
    print()
    print(f"Config file:  {Config.config_file_path()}")
    print(f"Database:     {Config.database_path()}")
    print(f"Spam model:   {Config.spam_model_path()}")
