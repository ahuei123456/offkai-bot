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
  - Set maximum capacity limits for events
  - Modify event details after creation
  - Open/close event registrations
  - Archive old events

- **👥 Attendance Tracking**
  - Interactive Discord buttons for attendance confirmation
  - Support for bringing extra people (+0 to +5 guests)
  - Behavior and arrival time confirmations
  - Optional drink preferences tracking
  - View current attendance count and attendee list

- **📋 Waitlist System**
  - Automatic waitlist when events reach capacity
  - FIFO (First In, First Out) promotion from waitlist
  - Batch promotion when multiple spots open up
  - Waitlist joins for groups that exceed remaining capacity
  - Join waitlist after registration deadline or when event is closed

- **🔔 Smart Notifications**
  - DM notifications for successful registrations
  - DM notifications when promoted from waitlist
  - DM notifications when withdrawing from events
  - Fallback to ephemeral channel messages if DMs are disabled
  - Thread notifications when capacity is reached

- **🎯 Registration Controls**
  - Prevent duplicate registrations (same user can't register twice for same event)
  - Cross-list duplicate prevention (can't be in both responses and waitlist)
  - Event isolation (registrations are per-event)
  - Withdrawal with automatic waitlist promotion
  - Withdrawal allowed even after event is closed or deadline passed

- **💬 Communication Tools**
  - Broadcast messages to all event attendees
  - Thread-based event discussions
  - Automatic thread management (add/remove users)
  - Pin important event messages

- **🗑️ Management Commands**
  - Delete individual user responses
  - View drinks summary for catering
  - Archive completed events

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
       "WAITLIST_FILE": "data/waitlist.json",
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
   | `RESPONSES_FILE` | string | ✅ | Path to responses data file (e.g., `data/responses.json`) |
   | `WAITLIST_FILE` | string | ✅ | Path to waitlist data file (e.g., `data/waitlist.json`) |
   | `GUILDS` | array | ✅ | List of Discord server IDs where bot will be active |

3. **Data Directory:**

   The bot will automatically create the `data/` directory and JSON files if they don't exist.

### Running the Bot

**Basic command:**
```bash
uv run offkai-bot
```

**With custom config path:**
```bash
uv run offkai-bot --config-path /path/to/config.json
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
  - Parameters: name, venue, address, maps_link, datetime, deadline (optional), drinks (optional), max_capacity (optional)

- `/modify_offkai` - Modify an existing event
  - Parameters: event_name, new details (venue, address, datetime, etc.)

- `/close_offkai` - Close event registrations
  - Parameters: event_name, close_msg (optional)

- `/reopen_offkai` - Reopen event registrations
  - Parameters: event_name, reopen_msg (optional)

- `/archive_offkai` - Archive a completed event
  - Parameters: event_name

### Attendance Management

- `/attendance` - View list of attendees
  - Parameters: event_name

- `/drinks` - View drinks summary
  - Parameters: event_name

- `/delete_response` - Remove a user's registration
  - Parameters: event_name, member

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

# Run tests in watch mode
uv run pytest-watch

# Check code quality
uvx ruff check .
uvx mypy src/
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

**License:** [Specify your license]

**Maintainers:** [List maintainers]

**Support:** For questions, join our Discord server or open a discussion on GitHub.
