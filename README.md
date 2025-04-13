# What is Offkai Bot?

A bot designed to simplify the process of attendance gathering for big gatherings. Our current usecase is mainly for large group dinners after lives/concerts/other events, so thus the name "Offkai Bot".

This bot is aimed to replace the previous manual methods of collating attendance for offkais, including and not limited to Google Forms surveys, collecting reactions on a Discord message, and waiting for replies of "I'm attending". Previous challenges faced have included errors in keeping track of attendees and attendees not receiving updates for various reasons, which this bot hopes to solve.

## Installation

Offkai bot uses uv for managing the environment and dependencies
please refer to uv website for installation and more information

https://docs.astral.sh/uv/getting-started/installation/

To run the bot simply run the command

```
uv run offkai-bot --config-path /path/to/config/file
```

## Configuration

The bot requires a `config.json` file in the project's root directory to store essential settings. The `bot/config.py` script loads these settings.

**`config.json` Format:**

```json
{
    "DISCORD_TOKEN": "YOUR_BOT_TOKEN_HERE",
    "EVENTS_FILE": "data/events.json",
    "RESPONSES_FILE": "data/responses.json",
    "GUILDS": [
        111111111111111111,
        122222222222222222
    ]
}
```

**Fields:**

*   `DISCORD_TOKEN` (string): **Required.** Your Discord bot's secret token. **Keep this confidential!** Do not commit it directly to public repositories.
*   `EVENTS_FILE` (string): **Required.** The relative path from the project root to the JSON file where event data is stored (e.g., `data/events.json`). The bot will create this file if it doesn't exist.
*   `RESPONSES_FILE` (string): **Required.** The relative path from the project root to the JSON file where user response data is stored (e.g., `data/responses.json`). The bot will create this file if it doesn't exist.
*   `GUILDS` (list of integers): **Required.** A list of Discord Server (Guild) IDs where the slash commands should be synced immediately on startup. These servers are where the bot will be active in.
