# Project: Offkai Bot

## 1. Project Overview & Tech Stack
**Context Source:** `pyproject.toml`, `README.md`
- **Core Concept**: A Discord bot for managing event attendance, waitlists, and notifications for "Offkai" gatherings.
- **Language**: Python 3.12+ (Strictly Typed)
- **Framework**: `discord.py`
- **Package Manager**: `uv` (Used for dependency management and running the bot/tools)
- **Linting/Formatting**: `ruff`
- **Type Checking**: `mypy` (Strict mode)
- **Testing**: `pytest` + `pytest-asyncio`

## 2. Architecture & Key Patterns
**Context Source:** `src/offkai_bot/`

### Entry Point & Commands
- **`main.py`**: Initializes `OffkaiClient`, loads data, registers slash commands (`@client.tree.command`), and handles global errors (`on_command_error`).
- **Command Pattern**:
    - Commands are defined in `main.py` but delegate logic to `event_actions.py` or `data/` modules.
    - **@log_command_usage**: Decorator used on all commands to ensure standardized logging.

### Data Layer
- **Location**: `src/offkai_bot/data/`
- **Storage**: Local JSON files (Events, Responses, Rankings).
- **Pattern**:
    - **Read-Through Caching**: Global variables (e.g., `EVENT_DATA_CACHE`) hold the in-memory state.
    - **Loaders**: `load_event_data()` ensures cache is populated.
    - **Savers**: `save_event_data()` serializes the cache back to JSON. atomic writes are favored.

### Interactions
- **Location**: `src/offkai_bot/interactions.py`
- **Components**: Handles Discord UI elements like Buttons (`ConfirmAttendance`, `JoinWaitlist`) and Modals.
- **Validation**: `validate_interaction_context` ensures commands run in the correct context (Guild vs DM).

## 3. Testing Strategy
**Context Source:** `tests/conftest.py`

- **Framework**: `pytest`
- **Key Fixtures**:
    - `mock_config`: **CRITICAL**. Uses `tmp_path_factory` to create isolated JSON files for each test module. preventing data pollution.
    - `clear_caches`: **Auto-use**. Resets global data caches (`EVENT_DATA_CACHE`, etc.) before and after every test.
    - `sample_event_list`: Provides standard `Event` objects for testing.
- **Mocking**: `unittest.mock` (`patch`, `AsyncMock`) is used extensively to mock Discord API calls (e.g., `thread.send`, `interaction.response`).

## 4. Agentic Workflows

### How to Add a New Slash Command
1.  **Define**: Create the function in `src/offkai_bot/main.py` decorated with `@client.tree.command`.
2.  **Decorate**: Apply `@log_command_usage` as the INNER decorator (closest to the function).
3.  **Validate**: Call `validate_interaction_context(interaction)` first.
4.  **Delegate**: Do not put complex logic in `main.py`. Call a function in `event_actions.py` or a specific data module.
5.  **Response**: Always provide an interaction response (ephemeral or public).

### How to Modify Data Schema
1.  **Update Model**: Modify the `Event` (or other) dataclass in `src/offkai_bot/data/event.py`.
2.  **Update Loader**: In `load_event_data` (same file), add logic to handle missing fields in old JSON files (e.g., `event_dict.get("new_field", default_value)`).
3.  **Update Saver**: Ensure `to_dict()` or the saving logic includes the new field.

### How to Define New Errors
1.  **Define**: Add a new class in `src/offkai_bot/errors.py`.
2.  **Inherit**: Must inherit from `BotCommandError` (for general errors) or a more specific base.
3.  **Log Level**: Set `self.log_level = logging.WARNING` (or ERROR) in `__init__` if needed.
4.  **Handle**: In `src/offkai_bot/main.py` -> `on_command_error`, add a `case YourNewError():` block if you need custom messaging, otherwise `BotCommandError` catch-all handles it.

## 5. Development Rules & Quality Gates
> [!IMPORTANT]
> All tasks must pass these gates before completion.

1.  **Pre-commit/Linting**:
    - Run: `uv run ruff check . --fix`
    - **Constraint**: No remaining lint errors allowed.
2.  **Type Checking**:
    - Run: `uv run mypy src/`
    - **Constraint**: Must be clean. No `type: ignore` unless absolutely necessary and justified.
3.  **Testing**:
    - Run: `uv run pytest`
    - **Constraint**: All tests must pass. New features must have associated tests.
