# src/offkai_bot/data/ranking.py
import json
import logging
import os
from dataclasses import dataclass, replace

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
        if not isinstance(username, str) or type(rank) is not int or rank < 0:
            raise ValueError("Invalid username or rank")
        if not all(type(value) is bool for value in (achieved_rank_1, achieved_rank_5, achieved_rank_10)):
            raise ValueError("Invalid ranking achievement flag")

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
    file_path = get_config()["RANKING_FILE"]
    if not os.path.exists(file_path):
        atomic_write_json(file_path, {}, indent=4)
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)
        if not isinstance(raw_data, dict):
            raise ValueError("Rankings data must be an object")
        ranking_dict: dict[str, UserRank] = {}
        for key, record in raw_data.items():
            if not isinstance(record, dict):
                raise ValueError(f"Invalid ranking record for {key}")
            ranking = _parse_ranking_from_dict(record)
            if ranking is None:
                raise ValueError(f"Invalid ranking record for {key}")
            ranking_dict[key] = ranking
    except (ValueError, TypeError, OSError):
        backup_corrupted_file(file_path)
        _log.exception("Cannot load rankings from %s; original data preserved.", file_path)
        raise
    RANKING_DATA_CACHE = ranking_dict
    return ranking_dict


def load_rankings() -> dict[str, UserRank]:
    if RANKING_DATA_CACHE is not None:
        return RANKING_DATA_CACHE
    else:
        return _load_rankings()


def save_rankings(data: dict[str, UserRank] | None = None) -> None:
    """Persist a supplied snapshot or the loaded cache; write failures propagate."""
    if data is None:
        data = RANKING_DATA_CACHE
    if data is None:
        raise RuntimeError("Attempted to save ranking data before loading")
    atomic_write_json(get_config()["RANKING_FILE"], data, indent=4, cls=DataclassJSONEncoder, ensure_ascii=False)


def _commit_rankings(staged: dict[str, UserRank]) -> None:
    current = load_rankings()
    save_rankings(staged)
    current.clear()
    current.update(staged)


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
        user_data = replace(user_data)
        all_data[key] = user_data
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
            migrated = replace(legacy_entry)
        else:
            _merge_rank_entries(migrated, legacy_entry)
        _log.info("Migrated legacy ranking entry '%s' to user ID %s (%s).", legacy_key, user_id, username)
    if migrated is not None:
        migrated.username = username
        all_data[key] = migrated
    return migrated


def migrate_legacy_rank(user_id: int, username: str, legacy_key: str) -> int:
    """Manually reassign a legacy username-keyed rank entry to a user, merging it
    into any existing ID-keyed entry. Returns the user's resulting rank.

    Raises:
        LegacyRankEntryNotFoundError: If no legacy entry exists under legacy_key.
    """
    all_data = load_rankings().copy()
    entry = all_data.get(legacy_key)
    # Long digit-only keys are ID-keyed entries, not legacy usernames; refuse to move them.
    if entry is None or (legacy_key.isdigit() and len(legacy_key) >= 15):
        raise LegacyRankEntryNotFoundError(legacy_key)

    del all_data[legacy_key]
    user_data = all_data.get(str(user_id))
    if user_data is None:
        user_data = replace(entry)
        all_data[str(user_id)] = user_data
    else:
        user_data = replace(user_data)
        all_data[str(user_id)] = user_data
        _merge_rank_entries(user_data, entry)
    user_data.username = username
    _commit_rankings(all_data)
    _log.info("Manually migrated legacy ranking entry '%s' to user ID %s (%s).", legacy_key, user_id, username)
    return user_data.rank


def update_rank(user_id: int, username: str) -> None:
    all_data = load_rankings().copy()
    user_data = _get_user_rank(all_data, user_id, username)
    if user_data is None:
        user_data = UserRank(
            username=username, rank=0, achieved_rank_1=False, achieved_rank_5=False, achieved_rank_10=False
        )
        all_data[str(user_id)] = user_data
    user_data.username = username
    user_data.rank += 1
    _commit_rankings(all_data)
    _log.info("Updated %s rank to %s.", username, user_data.rank)


def decrease_rank(user_id: int, username: str) -> None:
    all_data = load_rankings().copy()
    had_id_entry = str(user_id) in all_data
    user_data = _get_user_rank(all_data, user_id, username)
    if user_data and user_data.rank > 0:
        user_data.rank -= 1
        _commit_rankings(all_data)
        _log.info("Updated %s rank to %s.", username, user_data.rank)
    elif user_data is not None and not had_id_entry:
        _commit_rankings(all_data)


def get_rank(user_id: int, username: str) -> int:
    all_data = load_rankings().copy()
    had_id_entry = str(user_id) in all_data
    user_data = _get_user_rank(all_data, user_id, username)
    if user_data:
        if not had_id_entry:
            _commit_rankings(all_data)
        return user_data.rank
    else:
        user_data = UserRank(
            username=username, rank=0, achieved_rank_1=False, achieved_rank_5=False, achieved_rank_10=False
        )
        all_data[str(user_id)] = user_data
        _commit_rankings(all_data)
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
    all_data = load_rankings().copy()
    user_data = all_data.get(str(user_id))
    if user_data:
        user_data = replace(user_data)
        all_data[str(user_id)] = user_data
        match user_data.rank:
            case 1:
                user_data.achieved_rank_1 = True
            case 5:
                user_data.achieved_rank_5 = True
            case 10:
                user_data.achieved_rank_10 = True
        _commit_rankings(all_data)
