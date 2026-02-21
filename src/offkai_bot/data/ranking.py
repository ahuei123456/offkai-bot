# src/offkai_bot/data/ranking.py
import json
import logging
import os
from dataclasses import dataclass

from offkai_bot.config import get_config
from offkai_bot.data.encoders import DataclassJSONEncoder

_log = logging.getLogger(__name__)


@dataclass
class UserRank:
    username: str
    rank: int
    achieved_rank_1: bool
    achieved_rank_5: bool
    achieved_rank_10: bool


RANKING_DATA_CACHE: dict[str, UserRank] | None = None


def _parse_ranking_from_dict(rank_dict: dict) -> UserRank | None:
    try:
        username = rank_dict.get("username", "Unknown User")
        rank = rank_dict.get("rank", 0)
        achieved_rank_1 = rank_dict.get("achieved_rank_1", False)
        achieved_rank_5 = rank_dict.get("achieved_rank_5", False)
        achieved_rank_10 = rank_dict.get("achieved_rank_10", False)

        return UserRank(
            username=username,
            rank=rank,
            achieved_rank_1=achieved_rank_1,
            achieved_rank_5=achieved_rank_5,
            achieved_rank_10=achieved_rank_10,
        )

    except (TypeError, ValueError) as e:
        _log.error(f"Error creating Response object for user from dict {rank_dict}: {e}")

    return None


def _load_rankings() -> dict[str, UserRank]:
    global RANKING_DATA_CACHE
    settings = get_config()
    ranking_dict: dict[str, UserRank] = {}
    file_path = settings["RANKING_FILE"]
    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise FileNotFoundError

        with open(file_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)

        if not isinstance(raw_data, dict):
            _log.error(
                f"Invalid format in {file_path}: "
                f"Expected a JSON object (dict), got {type(raw_data)}. Loading empty responses."
            )
            raw_data = {}

        for username, ranking_data in raw_data.items():
            if not isinstance(ranking_data, dict):
                _log.warning(
                    f"Invalid format for ranking '{ranking_data}' in {file_path}: "
                    f"Expected a dict with 'attendees'/'waitlist', got {type(ranking_data)}. Skipping."
                )
                continue

            ranking = _parse_ranking_from_dict(ranking_data)
            if ranking:
                ranking_dict[username] = ranking

    except FileNotFoundError:
        _log.warning(f"{file_path} not found or empty. Creating default empty file.")
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump({}, file, indent=4)
            _log.info(f"Created empty responses file at {file_path}")
        except OSError as e:
            _log.error(f"Could not create default responses file at {file_path}: {e}")
        RANKING_DATA_CACHE = {}
        return {}
    except json.JSONDecodeError:
        _log.error(
            f"Error decoding JSON from {file_path}. File might be corrupted or invalid. Loading empty responses."
        )
        RANKING_DATA_CACHE = {}
        return {}
    except Exception as e:
        _log.exception(f"An unexpected error occurred loading response data from {file_path}: {e}")
        RANKING_DATA_CACHE = {}
        return {}

    RANKING_DATA_CACHE = ranking_dict
    return ranking_dict


def load_rankings() -> dict[str, UserRank]:
    if RANKING_DATA_CACHE is not None:
        return RANKING_DATA_CACHE
    else:
        return _load_rankings()


def save_rankings():
    """Saves the current state of RANKING_DATA_CACHE to the JSON file in new format."""
    global RANKING_DATA_CACHE
    settings = get_config()
    if RANKING_DATA_CACHE is None:
        _log.error("Attempted to save response data before loading.")
        return

    try:
        with open(settings["RANKING_FILE"], "w", encoding="utf-8") as file:
            json.dump(
                RANKING_DATA_CACHE,
                file,
                indent=4,
                cls=DataclassJSONEncoder,
                ensure_ascii=False,
            )
    except OSError as e:
        _log.error(f"Error writing response data to {settings['RANKING_FILE']}: {e}")
    except Exception as e:
        _log.exception(f"An unexpected error occurred saving response data: {e}")


def update_rank(username: str) -> None:
    all_data = load_rankings()
    user_data = all_data.get(
        username,
        UserRank(username=username, rank=0, achieved_rank_1=False, achieved_rank_5=False, achieved_rank_10=False),
    )
    user_data.rank += 1
    if username not in all_data:
        all_data[username] = user_data
    save_rankings()
    _log.info(f"Updated {username} rank to {user_data.rank}.")


def decrease_rank(username: str) -> None:
    all_data = load_rankings()
    user_data = all_data.get(username, None)
    if user_data and user_data.rank > 0:
        user_data.rank -= 1
        all_data[username] = user_data
        save_rankings()
        _log.info(f"Updated {username} rank to {user_data.rank}.")


def get_rank(username: str) -> int:
    all_data = load_rankings()
    user_data = all_data.get(username, None)
    if user_data:
        return user_data.rank
    else:
        user_data = UserRank(
            username=username, rank=0, achieved_rank_1=False, achieved_rank_5=False, achieved_rank_10=False
        )
        all_data[username] = user_data
        save_rankings()
        _log.info(f"Created user rank for {username}.")
        return 0


def can_rank_message_sent(username: str) -> bool:
    all_data = load_rankings()
    user_data = all_data.get(username, None)
    if user_data:
        match user_data.rank:
            case 1:
                return not user_data.achieved_rank_1
            case 5:
                return not user_data.achieved_rank_5
            case 10:
                return not user_data.achieved_rank_10
    return False


def mark_achieved_rank(username: str) -> None:
    all_data = load_rankings()
    user_data = all_data.get(username, None)
    if user_data:
        match user_data.rank:
            case 1:
                user_data.achieved_rank_1 = True
            case 5:
                user_data.achieved_rank_5 = True
            case 10:
                user_data.achieved_rank_10 = True
        save_rankings()
