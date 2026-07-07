# src/offkai_bot/data/ranking.py
import json
import logging
import os
from dataclasses import dataclass

from offkai_bot.config import get_config
from offkai_bot.data.atomic import atomic_write_json, backup_corrupted_file
from offkai_bot.data.encoders import DataclassJSONEncoder
from offkai_bot.data.response import load_responses
from offkai_bot.errors import LegacyRankEntryNotFoundError

_log = logging.getLogger(__name__)


@dataclass
class UserRank:
    username: str
    rank: int
    achieved_rank_1: bool
    achieved_rank_5: bool
    achieved_rank_10: bool


# Keyed by str(user_id); legacy entries keyed by username are migrated lazily on access.
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
        _log.error("Error creating Response object for user from dict %s: %s", rank_dict, e)

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
                "Invalid format in %s: Expected a JSON object (dict), got %s. Loading empty responses.",
                file_path,
                type(raw_data),
            )
            raw_data = {}

        for username, ranking_data in raw_data.items():
            if not isinstance(ranking_data, dict):
                _log.warning(
                    "Invalid format for ranking '%s' in %s: "
                    "Expected a dict with 'attendees'/'waitlist', got %s. Skipping.",
                    ranking_data,
                    file_path,
                    type(ranking_data),
                )
                continue

            ranking = _parse_ranking_from_dict(ranking_data)
            if ranking:
                ranking_dict[username] = ranking

    except FileNotFoundError:
        _log.warning("%s not found or empty. Creating default empty file.", file_path)
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump({}, file, indent=4)
            _log.info("Created empty responses file at %s", file_path)
        except OSError as e:
            _log.error("Could not create default responses file at %s: %s", file_path, e)
        RANKING_DATA_CACHE = {}
        return {}
    except json.JSONDecodeError:
        _log.error(
            "Error decoding JSON from %s. File might be corrupted or invalid. Loading empty responses.", file_path
        )
        backup_corrupted_file(file_path)
        RANKING_DATA_CACHE = {}
        return {}
    except Exception as e:
        _log.exception("An unexpected error occurred loading response data from %s: %s", file_path, e)
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
        atomic_write_json(
            settings["RANKING_FILE"],
            RANKING_DATA_CACHE,
            indent=4,
            cls=DataclassJSONEncoder,
            ensure_ascii=False,
        )
    except OSError as e:
        _log.error("Error writing response data to %s: %s", settings["RANKING_FILE"], e)
    except Exception as e:
        _log.exception("An unexpected error occurred saving response data: %s", e)


def _registered_identities() -> list[tuple[int, str]]:
    """(user_id, username) pairs from every stored response and waitlist entry."""
    identities: list[tuple[int, str]] = []
    for event_data in load_responses().values():
        for entry in [*event_data["attendees"], *event_data["waitlist"]]:
            identities.append((entry.user_id, entry.username))
    return identities


def _legacy_owner_ids(username: str) -> set[int]:
    """User IDs that have registered under a username, per stored responses."""
    return {user_id for user_id, name in _registered_identities() if name == username}


def _usernames_for_user(user_id: int) -> set[str]:
    """Every username a user has registered under, per stored responses."""
    return {name for uid, name in _registered_identities() if uid == user_id}


def _merge_rank_entries(target: UserRank, other: UserRank) -> None:
    target.rank += other.rank
    target.achieved_rank_1 = target.achieved_rank_1 or other.achieved_rank_1
    target.achieved_rank_5 = target.achieved_rank_5 or other.achieved_rank_5
    target.achieved_rank_10 = target.achieved_rank_10 or other.achieved_rank_10


def _get_user_rank(all_data: dict[str, UserRank], user_id: int, username: str) -> UserRank | None:
    """Look up a user's entry by ID, migrating legacy username-keyed entries whose
    ownership stored responses can prove.

    A legacy key is claimed only when this user is the only user ID ever to have
    registered under that username, so a freed username reclaimed by someone else
    cannot inherit the previous holder's rank. Unprovable or ambiguous entries stay
    under their username key for manual migration via /migrate_rank.
    """
    key = str(user_id)
    user_data = all_data.get(key)
    if user_data is not None:
        return user_data

    # Once every entry is ID-keyed there is nothing left to migrate.
    if all(k.isdigit() for k in all_data):
        return None

    # Candidate legacy keys: the current username plus any name this user has
    # registered under (recovers entries stranded by a rename).
    migrated: UserRank | None = None
    for legacy_key in sorted({username} | _usernames_for_user(user_id)):
        legacy_entry = all_data.get(legacy_key)
        if legacy_entry is None or _legacy_owner_ids(legacy_key) != {user_id}:
            continue
        del all_data[legacy_key]
        if migrated is None:
            migrated = legacy_entry
        else:
            _merge_rank_entries(migrated, legacy_entry)
        _log.info("Migrated legacy ranking entry '%s' to user ID %s (%s).", legacy_key, user_id, username)
    if migrated is not None:
        migrated.username = username
        all_data[key] = migrated
        save_rankings()
    return migrated


def migrate_legacy_rank(user_id: int, username: str, legacy_key: str) -> int:
    """Manually reassign a legacy username-keyed rank entry to a user, merging it
    into any existing ID-keyed entry. Returns the user's resulting rank.

    Raises:
        LegacyRankEntryNotFoundError: If no legacy entry exists under legacy_key.
    """
    all_data = load_rankings()
    entry = all_data.get(legacy_key)
    # Long digit-only keys are ID-keyed entries, not legacy usernames; refuse to move them.
    if entry is None or (legacy_key.isdigit() and len(legacy_key) >= 15):
        raise LegacyRankEntryNotFoundError(legacy_key)

    del all_data[legacy_key]
    user_data = all_data.get(str(user_id))
    if user_data is None:
        user_data = entry
        all_data[str(user_id)] = user_data
    else:
        _merge_rank_entries(user_data, entry)
    user_data.username = username
    save_rankings()
    _log.info("Manually migrated legacy ranking entry '%s' to user ID %s (%s).", legacy_key, user_id, username)
    return user_data.rank


def update_rank(user_id: int, username: str) -> None:
    all_data = load_rankings()
    user_data = _get_user_rank(all_data, user_id, username)
    if user_data is None:
        user_data = UserRank(
            username=username, rank=0, achieved_rank_1=False, achieved_rank_5=False, achieved_rank_10=False
        )
        all_data[str(user_id)] = user_data
    user_data.username = username
    user_data.rank += 1
    save_rankings()
    _log.info("Updated %s rank to %s.", username, user_data.rank)


def decrease_rank(user_id: int, username: str) -> None:
    all_data = load_rankings()
    user_data = _get_user_rank(all_data, user_id, username)
    if user_data and user_data.rank > 0:
        user_data.rank -= 1
        save_rankings()
        _log.info("Updated %s rank to %s.", username, user_data.rank)


def get_rank(user_id: int, username: str) -> int:
    all_data = load_rankings()
    user_data = _get_user_rank(all_data, user_id, username)
    if user_data:
        return user_data.rank
    else:
        user_data = UserRank(
            username=username, rank=0, achieved_rank_1=False, achieved_rank_5=False, achieved_rank_10=False
        )
        all_data[str(user_id)] = user_data
        save_rankings()
        _log.info("Created user rank for %s.", username)
        return 0


def can_rank_message_sent(user_id: int) -> bool:
    all_data = load_rankings()
    user_data = all_data.get(str(user_id))
    if user_data:
        match user_data.rank:
            case 1:
                return not user_data.achieved_rank_1
            case 5:
                return not user_data.achieved_rank_5
            case 10:
                return not user_data.achieved_rank_10
    return False


def mark_achieved_rank(user_id: int) -> None:
    all_data = load_rankings()
    user_data = all_data.get(str(user_id))
    if user_data:
        match user_data.rank:
            case 1:
                user_data.achieved_rank_1 = True
            case 5:
                user_data.achieved_rank_5 = True
            case 10:
                user_data.achieved_rank_10 = True
        save_rankings()
