# =============================================================================
# Password Input Screen
# =============================================================================
# A modal screen for entering account passwords when they are not found
# in the system keyring.
#
# The password is returned to the caller and stored in the keyring for
# future use.
# =============================================================================

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static, Input, Button
from textual.containers import Vertical, Horizontal


class PasswordScreen(ModalScreen[str | None]):
    """
    Modal screen for password input.

    This screen is displayed when an account's password is not found
    in the system keyring. The user can enter their password, which
    will be stored in the keyring for future use.

    Returns:
        The entered password string, or None if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit", show=False),
    ]

    CSS = """
    PasswordScreen {
        align: center middle;
    }

    #password-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    #password-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #password-info {
        margin-bottom: 1;
        color: $text-muted;
    }

    #password-input {
        margin-bottom: 1;
    }

    #password-buttons {
        align: center middle;
        height: auto;
    }

    #password-buttons Button {
        margin: 0 1;
    }

    #password-error {
        color: $error;
        text-align: center;
        margin-bottom: 1;
        height: auto;
    }
    """

    def __init__(
        self,
        account_name: str,
        email: str,
        error_message: str = "",
    ) -> None:
        """
        Initialize the password screen.

        Args:
            account_name: Name of the account needing password.
            email: Email address for the account.
            error_message: Optional error message to display (e.g., "Invalid password").
        """
        super().__init__()
        self._account_name = account_name
        self._email = email
        self._error_message = error_message

    def compose(self) -> ComposeResult:
        """Compose the password dialog."""
        with Vertical(id="password-dialog"):
            yield Static("Enter Password", id="password-title")
            yield Static(
                f"Account: {self._account_name}\nEmail: {self._email}",
                id="password-info",
            )
            if self._error_message:
                yield Static(self._error_message, id="password-error")
            yield Input(
                placeholder="Password",
                password=True,
                id="password-input",
            )
            with Horizontal(id="password-buttons"):
                yield Button("Submit", id="submit-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        """Focus the password input when mounted."""
        self.query_one("#password-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "submit-btn":
            self.action_submit()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input field."""
        self.action_submit()

    def action_submit(self) -> None:
        """Submit the password."""
        password_input = self.query_one("#password-input", Input)
        password = password_input.value.strip()
        if password:
            self.dismiss(password)
        else:
            self.notify("Password cannot be empty", severity="warning")

    def action_cancel(self) -> None:
        """Cancel and return None."""
        self.dismiss(None)
