import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

_log = logging.getLogger(__name__)

_config_cache: dict[str, Any] | None = None  # Store the loaded config here

# Load environment variables from .env file at startup
load_dotenv()


class ConfigError(Exception):
    """Custom exception for configuration errors."""

    pass


def load_config(path: str = "config.json") -> dict[str, Any]:
    """Loads configuration from a JSON file and environment variables."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    data: dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f, object_hook=lambda d: dict(**d))
        except json.JSONDecodeError as e:
            raise ConfigError(f"Error decoding JSON from {path}: {e}")
        except Exception as e:
            raise ConfigError(f"An error occurred loading configuration from {path}: {e}")

    # Override or populate from environment variables if present
    if "DISCORD_TOKEN" in os.environ:
        data["DISCORD_TOKEN"] = os.environ["DISCORD_TOKEN"]
    if "GUILDS" in os.environ:
        guilds_raw = os.environ["GUILDS"]
        try:
            if guilds_raw.strip().startswith("["):
                data["GUILDS"] = json.loads(guilds_raw)
            else:
                data["GUILDS"] = [int(g.strip()) for g in guilds_raw.split(",") if g.strip()]
        except Exception as e:
            _log.error("Failed to parse GUILDS from environment: %s", e)

    # Allow setting file paths from env
    for file_key, env_var, default_val in [
        ("EVENTS_FILE", "EVENTS_FILE", "data/events.json"),
        ("RESPONSES_FILE", "RESPONSES_FILE", "data/responses.json"),
        ("WAITLIST_FILE", "WAITLIST_FILE", "data/waitlist.json"),
        ("RANKING_FILE", "RANKING_FILE", "data/ranking.json"),
        ("LOG_FILE", "LOG_FILE", "logs/offkai-bot.log"),
    ]:
        if file_key not in data:
            data[file_key] = os.environ.get(env_var, default_val)

    # --- Basic Validation ---
    required_keys = ["DISCORD_TOKEN", "EVENTS_FILE", "RESPONSES_FILE", "RANKING_FILE", "GUILDS"]
    for key in required_keys:
        if key not in data or not data[key]:
            raise ConfigError(f"Missing required configuration '{key}' (not in {path} or env)")
    # -----------------------------------------------------

    _config_cache = data
    _log.info("Configuration loaded successfully")
    return _config_cache


def get_config() -> dict[str, Any]:
    """Returns the loaded configuration, loading it if necessary."""
    if _config_cache is None:
        # Attempt to load with default path if not loaded yet
        # Alternatively, raise an error if explicit load hasn't happened
        # raise ConfigError("Configuration has not been loaded. Call load_config() first.")
        _log.warning("Config accessed before explicit load. Loading with default path.")
        load_config()  # Load with default path "config.json"

    if _config_cache is None:
        # This should ideally not be reachable if load_config works or raises
        raise ConfigError("Configuration is not available.")

    return _config_cache


# --- Remove the top-level loading and constants ---
# with open("config.json") as f:
#     config = json.load(f)
# DISCORD_TOKEN = config["DISCORD_TOKEN"]
# ... etc ...
