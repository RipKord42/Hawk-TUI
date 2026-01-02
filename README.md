# Hawk-TUI

> *The hawk sees all... especially your unread emails.*

A TUI (Terminal User Interface) email client that renders HTML emails with full styling and inline images, just like a GUI client — but in your terminal.

## Features

- **HTML Email Rendering**: View HTML emails with proper formatting and inline images using terminal graphics (Sixel/Kitty protocol)
- **Multi-Account Support**: Manage multiple email accounts in a unified interface
- **IMAP with IDLE Push**: Real-time notifications when new mail arrives — no polling needed
- **Full Offline Sync**: All emails are synced to a local SQLite database for offline access
- **SMTP Sending**: Compose, reply, and forward emails with your preferred editor
- **Client-Side Spam Filter**: Bayesian spam classifier that learns from your "Mark as Junk" actions
- **XDG Compliant**: Configuration and data files follow the XDG Base Directory specification

## Requirements

- Python 3.11+
- A terminal with good Unicode support
- For image rendering: a terminal that supports Sixel or Kitty graphics protocol (foot, kitty, wezterm, etc.)

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/hawk-tui.git
cd hawk-tui

# Install in development mode
pip install -e .

# Or install with browser rendering support (for complex HTML emails)
pip install -e ".[browser]"

# If using browser rendering, install Chromium
playwright install chromium
```

## Configuration

1. Copy the example config:
   ```bash
   mkdir -p ~/.config/hawk-tui
   cp config.example.toml ~/.config/hawk-tui/config.toml
   ```

2. Edit the config with your account details:
   ```bash
   $EDITOR ~/.config/hawk-tui/config.toml
   ```

3. Store your password securely in the keyring:
   ```bash
   keyring set hawk-tui:personal your@email.com
   # Enter password when prompted
   ```

## Usage

```bash
# Run Hawk-TUI
hawk-tui

# Or run as a Python module
python -m hawk_tui

# Show configuration paths
hawk-tui --paths

# Show version
hawk-tui --version
```

## Keybindings

### Navigation
- `j/k` or `↓/↑` - Navigate messages
- `Tab` - Switch focus between panels
- `Enter` - Open/select

### Message Actions
- `r` - Reply
- `R` - Reply All
- `d` - Delete (move to Trash)
- `*` - Toggle star
- `J` - Mark as Junk (trains spam filter)
- `!` - Mark as Not Junk

### Global
- `Ctrl+r` - Sync all accounts
- `v` - View HTML in browser
- `Ctrl+p` - Command palette
- `q` - Quit

## Architecture

```
hawk_tui/
├── core/           # Domain models (Account, Folder, Message)
├── imap/           # IMAP client, sync, and IDLE push
├── smtp/           # SMTP client for sending
├── storage/        # SQLite database layer
├── rendering/      # HTML→terminal rendering
├── spam/           # Bayesian spam classifier
└── ui/             # Textual TUI components
    ├── screens/    # Full-screen views
    ├── widgets/    # Reusable components
    └── styles/     # Textual CSS
```

## XDG Directories

Hawk-TUI follows the XDG Base Directory specification:

| Type   | Default Location                  | Contents                    |
|--------|-----------------------------------|-----------------------------|
| Config | `~/.config/hawk-tui/`             | `config.toml`               |
| Data   | `~/.local/share/hawk-tui/`        | SQLite database, spam model |
| Cache  | `~/.cache/hawk-tui/`              | Rendered content cache      |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/

# Type checking
mypy src/
```

## License

MIT

## Credits

Built with:
- [Textual](https://textual.textualize.io/) - TUI framework
- [aioimaplib](https://github.com/bamthomas/aioimaplib) - Async IMAP
- [aiosmtplib](https://github.com/cole/aiosmtplib) - Async SMTP
- [inscriptis](https://github.com/weblyzard/inscriptis) - HTML→text conversion
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) - HTML parsing
- [Pillow](https://pillow.readthedocs.io/) - Image processing
