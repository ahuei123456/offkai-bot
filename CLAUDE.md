# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Discord bot for managing event attendance at group gatherings (offkais). Handles RSVPs, waitlists, drink preferences, capacity limits, and deadline reminders via Discord threads, modals, and buttons.

## Commands

```bash
# Run tests
uv run pytest
uv run pytest tests/data/test_event.py              # single file
uv run pytest tests/data/test_event.py::test_name   # single test

# Lint and format
uvx ruff check --fix .
uvx ruff format .

# Type check
uvx mypy src/ --extra-checks --warn-unused-ignores --pretty
```

**Note:** Always use `uv`, never `python3` directly. There is a pre-existing mypy error in `src/offkai_bot/alerts/alerts.py:5` (unused type: ignore comment) — not related to new changes.

## Architecture

### Data Flow

1. `/create_offkai` slash command → creates Discord thread → `add_event()` → `send_event_message()` with buttons
2. User clicks "Confirm Attendance" button → `GatheringModal` shown → `on_submit()` validates inputs
3. If under capacity and before deadline: `add_response()` → DM confirmation
4. If at/over capacity or past deadline: `add_to_waitlist()` → DM waitlist confirmation
5. On withdrawal: `remove_response()` → `promote_waitlist_batch()` (FIFO) → DM promoted users

### Key Modules

- **`cogs/events.py`** — Slash commands (`/create_offkai`, `/modify_offkai`, `/close_offkai`, `/promote`, `/attendance`, etc.). Admin-facing, requires "Offkai Organizer" role.
- **`interactions.py`** — Discord UI: `GatheringModal` (modal for registration), `OpenEvent`/`ClosedEvent`/`PostDeadlineEvent` (button views), `promote_waitlist_batch()`. User-facing DM messages live here.
- **`event_actions.py`** — Orchestration: `send_event_message()`, `update_event_message()`, `fetch_thread_for_event()`, `register_deadline_reminders()`, `load_and_update_events()` (startup).
- **`data/event.py`** — `Event` dataclass, `OFFKAI_MESSAGE` constant, `EVENT_DATA_CACHE`, JSON persistence.
- **`data/response.py`** — `Response` and `WaitlistEntry` dataclasses (nearly identical fields), `RESPONSE_DATA_CACHE`, unified JSON storage with `{"event_name": {"attendees": [...], "waitlist": [...]}}`.
- **`errors.py`** — Custom exception hierarchy rooted at `BotCommandError`.
- **`alerts/`** — Scheduled task system for deadline reminders and auto-close.

### Conventions

- **`@log_command_usage`**: Decorator applied to all slash commands for standardized logging.
- **`validate_interaction_context(interaction)`**: Called at the start of commands to ensure correct context (Guild vs DM).
- Commands delegate complex logic to `event_actions.py` or `data/` modules — keep command handlers thin.

### Data Layer Patterns

- **In-memory caches**: Global module-level (`EVENT_DATA_CACHE`, `RESPONSE_DATA_CACHE`). Load on first access, mutate in place, call `save_*()` explicitly.
- **Timezone handling**: User input assumed JST, stored as UTC, displayed as JST. Use `datetime.now(UTC)` for comparisons.
- **JSON serialization**: `DataclassJSONEncoder` converts dataclasses via `asdict()`, datetimes to ISO strings.
- **Capacity**: `sum(1 + r.extra_people for r in responses)` — each response can bring 0-5 guests.

### Test Patterns

- Tests use `unittest.mock` extensively for Discord objects.
- Key fixtures in `conftest.py`: `mock_paths` (temp file paths), `prepopulated_event_cache` (pre-filled cache), `clear_caches` (auto-resets global caches), `mock_thread`.
- `asyncio_mode = "auto"` — async tests work without explicit decorators.

## Common Workflows

### Adding a New Slash Command
1. Define in `cogs/events.py` with `@app_commands.command` and `@app_commands.checks.has_role("Offkai Organizer")`.
2. Apply `@log_command_usage` as the innermost decorator (closest to the function).
3. Call `validate_interaction_context(interaction)` first.
4. Delegate logic to `event_actions.py` or data modules — don't put complex logic in the command handler.
5. Always provide an interaction response (ephemeral or public).

### Modifying Data Schema
1. Update the dataclass in `data/event.py` (or `data/response.py`).
2. Update the loader (e.g., `_load_event_data`) to handle missing fields in old JSON via `event_dict.get("new_field", default)`.
3. Ensure `DataclassJSONEncoder` (uses `asdict()`) covers the new field.

### Defining New Errors
1. Add class in `errors.py`, inheriting from `BotCommandError`.
2. Set `self.log_level` in `__init__` if non-default level needed.
3. The global error handler in `main.py` handles `BotCommandError` generically; add a specific `case` only if custom messaging is needed.

## Configuration

- `config.json` at project root with keys: `DISCORD_TOKEN`, `EVENTS_FILE`, `RESPONSES_FILE`, `RANKING_FILE`, `GUILDS`.
- Accessed via `get_config()` singleton.

## Style

- Line length: 120 characters
- Target: Python 3.12
