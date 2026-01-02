# =============================================================================
# Account Model
# =============================================================================
# Represents an email account configuration. This includes connection details
# for both IMAP (receiving) and SMTP (sending) servers.
#
# IMPORTANT: Passwords are NOT stored here. They are retrieved from the system
# keyring at runtime using the 'keyring' library. This keeps credentials secure
# and out of config files.
# =============================================================================

from dataclasses import dataclass, field


@dataclass
class Account:
    """
    Represents an email account with IMAP and SMTP configuration.

    Attributes:
        name: A unique identifier for this account (e.g., "personal", "work").
              Used as the key in config files and for keyring lookups.
        email: The email address associated with this account.
        display_name: The name shown in the "From" field when sending emails.
                      Defaults to the email address if not specified.

        imap_host: Hostname of the IMAP server (e.g., "imap.gmail.com").
        imap_port: Port for IMAP connection. Standard ports:
                   - 993 for IMAP with SSL/TLS (recommended)
                   - 143 for IMAP with STARTTLS
        imap_security: Connection security method ("ssl" or "starttls").

        smtp_host: Hostname of the SMTP server (e.g., "smtp.gmail.com").
        smtp_port: Port for SMTP connection. Standard ports:
                   - 465 for SMTP with SSL (older method)
                   - 587 for SMTP with STARTTLS (recommended)
        smtp_security: Connection security method ("ssl" or "starttls").

        id: Database primary key. None until the account is saved to storage.
        enabled: Whether this account is active. Disabled accounts won't sync.

    Example:
        >>> account = Account(
        ...     name="personal",
        ...     email="user@example.com",
        ...     display_name="John Doe",
        ...     imap_host="imap.example.com",
        ...     imap_port=993,
        ...     smtp_host="smtp.example.com",
        ...     smtp_port=587,
        ... )
    """

    # Account identification
    name: str                           # Unique account identifier
    email: str                          # Email address
    display_name: str = ""              # Name shown in "From" field

    # IMAP configuration (for receiving emails)
    imap_host: str = ""
    imap_port: int = 993                # Default to SSL port
    imap_security: str = "ssl"          # "ssl" or "starttls"

    # SMTP configuration (for sending emails)
    smtp_host: str = ""
    smtp_port: int = 587                # Default to STARTTLS port
    smtp_security: str = "starttls"     # "ssl" or "starttls"

    # Database fields
    id: int | None = None               # Primary key (None until saved)
    enabled: bool = True                # Whether account is active

    def __post_init__(self) -> None:
        """
        Post-initialization processing.
        Sets display_name to email if not provided.
        """
        if not self.display_name:
            self.display_name = self.email

    @property
    def keyring_service(self) -> str:
        """
        Returns the service name used for keyring password storage.

        We use a consistent naming scheme so passwords can be easily
        managed via the keyring CLI if needed:
            keyring get hawk-tui:personal user@example.com
        """
        return f"hawk-tui:{self.name}"

    def __str__(self) -> str:
        """Human-readable representation showing account name and email."""
        return f"{self.name} <{self.email}>"

    def __repr__(self) -> str:
        """Developer-friendly representation with key fields."""
        return (
            f"Account(name={self.name!r}, email={self.email!r}, "
            f"imap={self.imap_host}:{self.imap_port}, "
            f"smtp={self.smtp_host}:{self.smtp_port})"
        )
