import json
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_config_cache: dict[str, Any] | None = None  # Store the loaded config here


class ConfigError(Exception):
    """Custom exception for configuration errors."""

    pass


def load_config(path: str = "config.json") -> dict[str, Any]:
    """Loads configuration from a JSON file."""
    global _config_cache
    if _config_cache is not None:
        # Optional: Decide if reloading is allowed or just return cache
        # _log.debug("Returning cached config")
        return _config_cache

    if not os.path.exists(path):
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with open(path) as f:
            # Use object_hook to load into a namespace for attribute access
            data = json.load(f, object_hook=lambda d: dict(**d))

        # --- Basic Validation (Optional but Recommended) ---
        required_keys = ["DISCORD_TOKEN", "EVENTS_FILE", "RESPONSES_FILE", "RANKING_FILE", "GUILDS"]
        for key in required_keys:
            if key not in data:
                raise ConfigError(f"Missing required key '{key}' in {path}")
        # Add more specific type checks if needed
        # Note: WAITLIST_FILE is optional for backward compatibility during migration
        # -----------------------------------------------------

        _config_cache = data
        _log.info(f"Configuration loaded successfully from {path}")  # Optional logging
        return _config_cache
    except json.JSONDecodeError as e:
        raise ConfigError(f"Error decoding JSON from {path}: {e}")
    except Exception as e:
        # Catch other potential errors during loading/validation
        raise ConfigError(f"An error occurred loading configuration: {e}")


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
