# Hawk-TUI Development TODO

## Current Status: Version 0.1.0 - Ready for Release

A fully functional TUI email client with IMAP/SMTP support, spam filtering, and real-time push notifications.

---

## Fully Implemented (v0.1.0)

### Core Infrastructure
- [x] Configuration management (XDG compliant)
- [x] SQLite database with async operations (WAL mode)
- [x] IMAP client (SSL/STARTTLS, folder listing, message fetching)
- [x] Multi-account support with keyring password storage
- [x] Password prompt dialog when credentials missing

### UI/Display
- [x] Main screen 3-pane layout (folder tree, message list, preview)
- [x] Folder tree with account grouping and folder type icons
- [x] Message list with read status, star, sender, subject, date
- [x] Message preview with headers and HTML content
- [x] HTML rendering as native Textual widgets
- [x] Clickable links in email preview
- [x] View HTML in browser (v key)
- [x] Folder unread counts with live updates

### Email Operations
- [x] Message viewing with full headers
- [x] Toggle read/unread (u key)
- [x] Toggle star/flag (* key)
- [x] Mark as junk (J key) / not junk (! key)
- [x] Delete messages (d/DEL key) - moves to Trash, permanent if in Trash
- [x] Empty Trash/Junk (E key)
- [x] IMAP sync with progress display (Ctrl+R)
- [x] Compose new email (c key)
- [x] Reply / Reply All / Forward (r/R/f keys)
- [x] Send email via SMTP
- [x] Save attachments (a key)
- [x] Multi-select with bulk operations (Space, Ctrl+A)
- [x] Search with FTS5 full-text (/ key)

### Sync Features
- [x] Folder list synchronization
- [x] Message fetching with batching (50 at a time)
- [x] Flag synchronization (server -> local)
- [x] New message detection
- [x] UIDVALIDITY handling
- [x] IDLE/Push support - Real-time notifications (monitors INBOX)
- [x] Smart incremental sync - Detects messages moved in from other clients
- [x] Progress display for large folders - Shows count during sync

### Spam Filtering
- [x] Naive Bayes classifier implementation
- [x] Token extraction from headers and body
- [x] Model persistence (save/load)
- [x] Manual training on J/! actions
- [x] Auto-move spam during sync

### Rendering
- [x] Fast HTML-to-widgets rendering
- [x] Image rendering via Kitty protocol (I key)
- [x] Browser rendering with Playwright

---

## Version 0.2.0

Future enhancements for the next release:

### Sync Improvements
- [ ] Bidirectional flag sync - Push local flag changes to server
- [ ] Time interval sync - Background sync at configurable intervals
- [ ] Deletion sync - Properly handle `sync.sync_deleted` config
- [ ] Max age filter - Honor `sync.max_age_days` config

### UI Enhancements
- [ ] Message list pagination - Virtual scrolling for folders with 1000+ messages
- [ ] Configurable color scheme - Theme customization beyond dark/light
- [ ] Settings screen - Edit config from within app
- [ ] Help screen - Full keybinding reference
- [ ] Sidebar toggle - Hide/show folder tree
- [ ] Theme support - Honor `ui.theme` (dark/light)
- [ ] Confirm delete - Honor `confirm_delete` config option

### Email Operations
- [ ] Move to folder - Press 'm' to move message(s) to selected folder (folder picker dialog)
- [ ] Copy to folder - Press 'C' to copy message(s) to selected folder

### Advanced Features
- [ ] Multi-account compose - Select "Send from" account when multiple exist
- [ ] Address completion - Autocomplete in compose fields
- [ ] Threading/conversations - Group related messages
- [ ] Signatures - Account-specific email signatures
- [ ] Draft saving - Save compose drafts to Drafts folder
- [ ] Mouse support for multi-select - Click and shift+click selection

### Code Quality
- [ ] Add unit tests
- [ ] Add integration tests for IMAP/SMTP
- [ ] Error handling improvements
- [ ] Logging configuration
- [ ] Performance profiling for large mailboxes

---

## Config Options Status

| Option | Status | Notes |
|--------|--------|-------|
| `general.default_account` | Partial | Loaded but not used for selection |
| `rendering.mode` | Working | `fast` and `browser` modes |
| `rendering.image_protocol` | Partial | Auto-detection not implemented |
| `spam.enabled` | Working | Classifier functional |
| `spam.threshold` | Working | Used in classification |
| `spam.auto_move_to_junk` | Working | Auto-moves spam during sync |
| `spam.train_on_move` | Working | Trains classifier on J/! actions |
| `sync.check_interval_minutes` | Not implemented | No background sync |
| `sync.use_idle` | Working | IDLE monitors INBOX for all accounts |
| `sync.sync_deleted` | Partial | Behavior unclear |
| `sync.max_age_days` | Not implemented | |
| `ui.theme` | Not implemented | Always dark |
| `ui.confirm_delete` | Not implemented | No confirmation |
| `ui.preview_lines` | Not implemented | |

---

## Architecture Notes

**Well-Structured:**
- Clean separation: `core/`, `imap/`, `smtp/`, `storage/`, `rendering/`, `ui/`, `spam/`
- Async/await throughout for non-blocking UI
- Type hints consistently used
- Comprehensive docstrings
- XDG compliance

**File Counts:**
- 36 Python files
- ~8,500+ lines of code

---

## Quick Reference

**Working Keybindings:**
- `q` - Quit
- `Ctrl+R` - Sync
- `j/k` or arrows - Navigate messages
- `Enter` - View message (preview)
- `c` - Compose new email
- `r` - Reply
- `R` - Reply all
- `f` - Forward
- `d` or `DEL` - Delete
- `*` - Toggle star
- `u` - Mark unread
- `J` - Mark as junk
- `!` - Mark as not junk
- `E` - Empty Trash/Junk folder
- `a` - Save attachments to ~/Downloads
- `v` - View HTML in browser
- `I` - Render as image (Playwright + Kitty)
- `x` or `Space` - Toggle select (sets anchor)
- `X` (shift+x) - Extend selection to current row
- `Ctrl+A` - Select all / Deselect all
- `Ctrl+A` (in compose) - Add attachment
- `/` - Search messages
- `Tab` - Switch panes
- `Ctrl+P` - Command palette
- `Escape` - Close palette/dialogs, clear selection

**Not Yet Working:**
- `Ctrl+S` - Settings (shows notification only)
