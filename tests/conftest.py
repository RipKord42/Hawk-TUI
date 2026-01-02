# =============================================================================
# Pytest Configuration and Fixtures
# =============================================================================
# Shared fixtures for the Hawk-TUI test suite.
# =============================================================================

import pytest
import tempfile
from pathlib import Path

from hawk_tui.core import Account, Folder, Message, FolderType, MessageFlags


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_account():
    """Create a sample Account for testing."""
    return Account(
        name="test",
        email="test@example.com",
        display_name="Test User",
        imap_host="imap.example.com",
        imap_port=993,
        imap_security="ssl",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_security="starttls",
    )


@pytest.fixture
def sample_folder():
    """Create a sample Folder for testing."""
    return Folder(
        name="INBOX",
        account_id=1,
        folder_type=FolderType.INBOX,
        uidvalidity=1234567890,
        total_messages=100,
        unread_count=5,
    )


@pytest.fixture
def sample_message():
    """Create a sample Message for testing."""
    from datetime import datetime

    return Message(
        folder_id=1,
        uid=12345,
        message_id="<test123@example.com>",
        subject="Test Subject",
        sender="sender@example.com",
        sender_name="Test Sender",
        recipients=["recipient@example.com"],
        date_sent=datetime(2024, 1, 15, 10, 30, 0),
        flags=MessageFlags.NONE,
        body_text="This is a test email body.",
        body_html="<html><body><p>This is a <b>test</b> email body.</p></body></html>",
    )


@pytest.fixture
def sample_html_email():
    """Sample HTML email content for rendering tests."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; }
            .header { background: #4a90d9; color: white; padding: 20px; }
            .content { padding: 20px; }
            .footer { background: #f5f5f5; padding: 10px; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Welcome to Our Newsletter!</h1>
        </div>
        <div class="content">
            <p>Hello <strong>User</strong>,</p>
            <p>This is a sample HTML email with various formatting:</p>
            <ul>
                <li>Bold text: <b>bold</b></li>
                <li>Italic text: <i>italic</i></li>
                <li>Links: <a href="https://example.com">Click here</a></li>
            </ul>
            <p>Here's an image:</p>
            <img src="cid:logo123" alt="Company Logo" width="200">
        </div>
        <div class="footer">
            <p>You received this email because you signed up at example.com</p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_spam_message():
    """Create a sample spam message for classifier testing."""
    from datetime import datetime

    return Message(
        folder_id=1,
        uid=99999,
        message_id="<spam@spammer.com>",
        subject="URGENT!!! You've WON $1,000,000!!! ACT NOW!!!",
        sender="winner@totallylegit.com",
        sender_name="Prize Department",
        recipients=["victim@example.com"],
        date_sent=datetime(2024, 1, 15, 10, 30, 0),
        flags=MessageFlags.NONE,
        body_text="""
        CONGRATULATIONS!!!

        You have been selected to receive $1,000,000 USD!!!

        Click here NOW to claim your prize: http://scam.example.com/prize

        ACT NOW - LIMITED TIME OFFER!!!

        Send your bank details to: scammer@fake.com
        """,
    )
