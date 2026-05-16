# Offkai Bot

A Discord bot designed to simplify attendance management for large group gatherings and events.

## Table of Contents

- [Motivation](#motivation)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [How to Run](#how-to-run)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Running the Bot](#running-the-bot)
- [Commands](#commands)
- [Reporting Issues](#reporting-issues)
- [Contributing](#contributing)

## Motivation

Offkai Bot was created to streamline the process of attendance gathering for large group events, particularly for dinners after lives, concerts, and other gatherings.

This bot replaces manual methods of collecting attendance such as:
- Google Forms surveys
- Collecting reactions on Discord messages
- Manually tracking "I'm attending" replies

**Previous challenges solved:**
- ✅ Errors in keeping track of attendees
- ✅ Attendees missing important updates
- ✅ Manual data entry and collation
- ✅ No automated notification system
- ✅ Difficulty managing capacity limits and waitlists

## Features

### Core Capabilities

- **📅 Event Management**
  - Create events with venue, address, Google Maps links, and deadlines
  - Set maximum capacity limits for events (with smart validation)
  - Modify event details including capacity (with safety checks)
  - Capacity increase allowed anytime, decrease only when safe
  - Cannot reduce capacity below current attendee count or with active waitlist
  - Open/close event registrations
  - Archive old events
  - Optional participant role: auto-assigned mentionable Discord role for attendees, auto-removed on withdrawal, auto-deleted on archive
  - Optional ping role for deadline reminders (7-day, 3-day, 24-hour)
  - Bilingual (English + Japanese) event messages, rules, DM notifications, and reminders

- **👥 Attendance Tracking**
  - Interactive Discord buttons for attendance confirmation
  - Support for bringing extra people (+0 to +5 guests)
  - Behavior and arrival time confirmations
  - Optional drink preferences tracking
  - Display name (nickname) capture and optional display in attendance/waitlist lists
  - View current attendance count and attendee list

- **📋 Waitlist System**
  - Automatic waitlist when events reach capacity
  - FIFO (First In, First Out) promotion from waitlist
  - Batch promotion when multiple spots open up
  - Waitlist joins for groups that exceed remaining capacity
  - Join waitlist after registration deadline or when event is closed

- **🔔 Smart Notifications**
  - DM notifications for successful registrations (with responsibility warnings)
  - DM notifications when promoted from waitlist (with responsibility warnings)
  - DM notifications when withdrawing from events (with post-deadline warnings)
  - Fallback to ephemeral channel messages if DMs are disabled
  - Thread notifications when capacity is reached
  - Clear warnings about post-deadline withdrawal consequences

- **🎯 Registration Controls**
  - Prevent duplicate registrations (same user can't register twice for same event)
  - Cross-list duplicate prevention (can't be in both responses and waitlist)
  - Event isolation (registrations are per-event)
  - Withdrawal with automatic waitlist promotion
  - Withdrawal allowed even after event is closed or deadline passed
  - Post-deadline withdrawal warnings inform users of their responsibilities
  - Unified data structure with automatic migration from legacy format

- **💬 Communication Tools**
  - Broadcast messages to all event attendees
  - Thread-based event discussions
  - Automatic thread management (add/remove users)
  - Pin important event messages

- **🗑️ Management Commands**
  - Delete individual user responses
  - View drinks summary for catering
  - Archive completed events

- **🏆 Ranking / Milestones**
  - Attendance milestone tracking (rank 1, 5, 10) with celebratory DM messages

### Data Architecture

- **Unified Storage Model**
  - Attendees and waitlist stored together in a single file per event
  - Each event contains separate `attendees` and `waitlist` arrays
  - Automatic migration from legacy separate-file format
  - Thread-safe operations with in-memory caching
  - JSON-based persistence for easy inspection and backup

- **Responsibility System**
  - All registrations include clear warnings about post-deadline withdrawals
  - Users informed of potential payment obligations and moderation consequences
  - Warnings shown at registration, waitlist join, and promotion
  - Post-deadline withdrawal messages emphasize user responsibility

- **Asynchronous Tasks & Alerts**
  - Robust background task scheduling system for automated event management
  - Clean separation of task definitions, execution loops, and event-specific reminder registration
  - Modular design prevents circular dependencies between core event actions and background jobs

## Prerequisites

Before running Offkai Bot, you need:

1. **Python 3.12 or higher**
   - Check your version: `python --version`

2. **uv (Python package manager)**
   - Install from: https://docs.astral.sh/uv/getting-started/installation/
   - Or quick install: `curl -LsSf https://astral.sh/uv/install.sh | sh`

3. **Discord Bot Token**
   - Create a bot at: https://discord.com/developers/applications
   - Enable required intents:
     - ✅ Server Members Intent
     - ✅ Message Content Intent (if using message features)
   - Copy the bot token for configuration

4. **Discord Server (Guild) ID**
   - Enable Developer Mode in Discord (User Settings > Advanced > Developer Mode)
   - Right-click your server and select "Copy Server ID"

## How to Run

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd offkai-bot
   ```

2. **Verify uv is installed:**
   ```bash
   uv --version
   ```

### Configuration

1. **Create a `config.json` file in the project root:**

   ```json
   {
       "DISCORD_TOKEN": "YOUR_BOT_TOKEN_HERE",
       "EVENTS_FILE": "data/events.json",
       "RESPONSES_FILE": "data/responses.json",
       "RANKING_FILE": "data/ranking.json",
       "LOG_FILE": "logs/offkai-bot.log",
       "GUILDS": [
           123456789012345678
       ]
   }
   ```

2. **Configuration Fields:**

   | Field | Type | Required | Description |
   |-------|------|----------|-------------|
   | `DISCORD_TOKEN` | string | ✅ | Your Discord bot token. **Keep this secret!** |
   | `EVENTS_FILE` | string | ✅ | Path to events data file (e.g., `data/events.json`) |
   | `RESPONSES_FILE` | string | ✅ | Path to responses data file (includes both attendees and waitlist) |
   | `RANKING_FILE` | string | ✅ | Path to ranking data file (e.g., `data/ranking.json`) |
   | `LOG_FILE` | string | ❌ | Path to bot log file (defaults to `logs/offkai-bot.log`; set to `null` to log only to console) |
   | `GUILDS` | array | ✅ | List of Discord server IDs where bot will be active |

   **Note:** The `WAITLIST_FILE` field is deprecated. Waitlist data is now stored in the responses file alongside attendee data. If you have an old `waitlist.json` file, it will be automatically migrated on first run.

3. **Data Directory:**

   The bot will automatically create the `data/` directory and JSON files if they don't exist.

4. **Log File:**

   The bot logs to both the console and `logs/offkai-bot.log` by default. When using Docker Compose, `./logs` is mounted into the container so the log file appears on the host.

### Running the Bot

**Basic command:**
```bash
uv run offkai-bot
```

**With custom config path:**
```bash
uv run offkai-bot --config-path /path/to/config.json
```

**With Docker Compose:**
```bash
docker compose up -d --build
docker compose logs -f discord-offkai-bot
```

**For development (with auto-reload):**
```bash
uv run python -m offkai_bot.main
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_event_actions.py

# Run with verbose output
uv run pytest -v

# Run with coverage
uv run pytest --cov=offkai_bot
```

### Code Quality Checks

```bash
# Run all pre-commit hooks (via prek)
uv run prek run --all-files

# Format code
uvx ruff format .

# Check linting
uvx ruff check .

# Type checking
uvx mypy src/ --extra-checks --warn-unused-ignores --pretty
```

## Commands

### Event Management

- `/create_offkai` - Create a new event
  - Parameters: name, venue, address, maps_link, datetime, deadline (optional), drinks (optional), max_capacity (optional), ping_role (optional), create_role (optional, default: False)

- `/modify_offkai` - Modify an existing event
  - Parameters: event_name, update_msg, venue (optional), address (optional), google_maps_link (optional), date_time (optional), deadline (optional), drinks (optional), max_capacity (optional)
  - Note: Capacity can be increased anytime, but can only be decreased if new capacity ≥ current attendee count AND waitlist is empty

- `/close_offkai` - Close event registrations
  - Parameters: event_name, close_msg (optional)

- `/reopen_offkai` - Reopen event registrations
  - Parameters: event_name, reopen_msg (optional)

- `/archive_offkai` - Archive a completed event
  - Parameters: event_name

### Attendance Management

- `/attendance` - View list of attendees
  - Parameters: event_name, sort (optional, default: False), nicknames (optional, default: False), drinks (optional, default: False; shows per-attendee drink choices)

- `/drinks` - View drinks summary
  - Parameters: event_name

- `/delete_response` - Remove a user's registration
  - Parameters: event_name, member

- `/promote` - Manually promote a user from the waitlist, bypassing capacity limits
  - Parameters: event_name, username (autocomplete)

- `/waitlist` - View waitlisted users
  - Parameters: event_name, sort (optional, default: False), nicknames (optional, default: False)

### Communication

- `/broadcast` - Send message to all attendees
  - Parameters: event_name, message

### Interactive Buttons

Users interact with events through Discord buttons:

- **"Confirm Attendance"** - Register for an event
- **"Withdraw Attendance"** - Cancel registration
- **"Join Waitlist"** - Join the waitlist when event is full or closed
- **"Attendance Count"** - View current registration count

## Reporting Issues

If you encounter bugs or issues:

1. **Check existing issues:** https://github.com/yourusername/offkai-bot/issues
2. **Create a new issue** with:
   - Clear description of the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Bot version and environment details
   - Relevant error messages or logs

**Issue Template:**
```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Run command '...'
2. Click on '...'
3. See error

**Expected behavior**
What you expected to happen.

**Environment:**
- OS: [e.g. Ubuntu 22.04]
- Python version: [e.g. 3.12.0]
- Discord.py version: [e.g. 2.3.2]

**Additional context**
Any other context about the problem.
```

## Contributing

We welcome contributions! Here's how you can help:

### Getting Started

1. **Fork the repository**
2. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes**
4. **Run tests and quality checks:**
   ```bash
   uv run pytest
   uvx ruff format .
   uvx ruff check .
   uvx mypy src/ --extra-checks --warn-unused-ignores --pretty
   ```
5. **Commit your changes:**
   ```bash
   git commit -m "Add: your feature description"
   ```
6. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```
7. **Create a Pull Request**

### Contribution Guidelines

- **Code Style:** Follow PEP 8, enforced by Ruff
- **Type Hints:** Use type hints for all functions
- **Tests:** Add tests for new features
- **Documentation:** Update README and docstrings
- **Commits:** Use clear, descriptive commit messages

### Development Setup

```bash
# Clone your fork
git clone https://github.com/yourusername/offkai-bot.git
cd offkai-bot

# Install development dependencies
uv sync

# Install git hooks (using prek)
uv run prek install

# Run tests in watch mode
uv run pytest-watch

# Check code quality
uv run prek run --all-files
```

### Areas for Contribution

- 🐛 Bug fixes
- ✨ New features
- 📝 Documentation improvements
- 🧪 Test coverage
- 🎨 UI/UX improvements
- 🌐 Localization/translations
- ⚡ Performance optimizations

### Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on the issue, not the person
- Help create a welcoming environment for all contributors

---

## License

This project is licensed under the MIT License - see below for details:

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
