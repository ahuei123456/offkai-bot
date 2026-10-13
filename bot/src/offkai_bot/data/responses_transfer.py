# src/offkai_bot/data/responses_transfer.py
"""Export the raw responses data and import an edited copy (for organizers without server access)."""

import json
import logging
import os
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

from offkai_bot.config import get_config
from offkai_bot.data import response as response_data
from offkai_bot.data.encoders import DataclassJSONEncoder
from offkai_bot.data.response import (
    EventData,
    Response,
    WaitlistEntry,
    _parse_response_from_dict,
    _parse_waitlist_entry_from_dict,
    load_responses,
    save_responses,
)
from offkai_bot.errors import ResponsesImportError

_log = logging.getLogger(__name__)

MAX_EXTRA_PEOPLE = 5


def export_responses_json() -> bytes:
    """Serialize the current responses data exactly as it is saved to disk."""
    return json.dumps(load_responses(), indent=4, cls=DataclassJSONEncoder, ensure_ascii=False).encode("utf-8")


def _require_valid_entry(raw_entry: object, event_name: str, section: str, index: int) -> dict[str, Any]:
    where = f"'{event_name}' {section} #{index + 1}"
    if not isinstance(raw_entry, dict):
        raise ResponsesImportError(f"{where} is not an object.")
    entry = cast(dict[str, Any], raw_entry)
    for key in ("user_id", "username", "timestamp"):
        if key not in entry or entry[key] in (None, ""):
            raise ResponsesImportError(f"{where} is missing '{key}'.")
    try:
        int(entry["user_id"])
        datetime.fromisoformat(entry["timestamp"])
    except (TypeError, ValueError):
        raise ResponsesImportError(f"{where} has an invalid user_id or timestamp.") from None
    extra_people = entry.get("extra_people", 0)
    if not isinstance(extra_people, int) or not 0 <= extra_people <= MAX_EXTRA_PEOPLE:
        raise ResponsesImportError(f"{where} has extra_people {extra_people!r}; it must be 0-{MAX_EXTRA_PEOPLE}.")
    extras_names = entry.get("extras_names", [])
    # Older registrations predate extras names, so an empty list is still accepted.
    if not isinstance(extras_names, list) or (extras_names and len(extras_names) != extra_people):
        raise ResponsesImportError(f"{where} needs exactly {extra_people} extras_names to match extra_people.")
    return entry


def parse_responses_import(raw: bytes) -> dict[str, EventData]:
    """Strictly parse an uploaded responses file.

    Unlike the startup loader, which skips bad entries, any problem rejects the
    whole upload so an edit can never silently drop someone's registration.
    """
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ResponsesImportError(f"The file is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise ResponsesImportError("The file must be a JSON object keyed by event name.")

    parsed: dict[str, EventData] = {}
    for event_name, event_data in data.items():
        if not isinstance(event_data, dict) or not set(event_data) <= {"attendees", "waitlist"}:
            raise ResponsesImportError(f"'{event_name}' must be an object with only 'attendees' and 'waitlist'.")
        sections = {section: event_data.get(section, []) for section in ("attendees", "waitlist")}
        if not all(isinstance(entries, list) for entries in sections.values()):
            raise ResponsesImportError(f"'{event_name}' attendees and waitlist must be lists.")

        attendees: list[Response] = []
        waitlist: list[WaitlistEntry] = []
        seen: set[int] = set()
        for section, entries in sections.items():
            for index, entry in enumerate(entries):
                valid = _require_valid_entry(entry, event_name, section, index)
                user_id = int(valid["user_id"])
                if user_id in seen:
                    raise ResponsesImportError(f"User {user_id} appears more than once in '{event_name}'.")
                seen.add(user_id)
                if section == "attendees":
                    response = _parse_response_from_dict(valid, event_name)
                    if response is None:
                        raise ResponsesImportError(f"'{event_name}' {section} #{index + 1} could not be read.")
                    attendees.append(response)
                else:
                    waitlisted = _parse_waitlist_entry_from_dict(valid, event_name)
                    if waitlisted is None:
                        raise ResponsesImportError(f"'{event_name}' {section} #{index + 1} could not be read.")
                    waitlist.append(waitlisted)
        parsed[event_name] = EventData(attendees=attendees, waitlist=waitlist)
    return parsed


def _snapshot(event_data: EventData) -> dict[int, tuple[str, str, str]]:
    """Map user_id -> (section, username, comparable JSON) for one event."""
    snapshot = {}
    for section, entries in (("attendee", event_data["attendees"]), ("waitlist", event_data["waitlist"])):
        for entry in entries:
            comparable = json.dumps(asdict(entry), cls=DataclassJSONEncoder, sort_keys=True, default=str)
            snapshot[entry.user_id] = (section, entry.username, comparable)
    return snapshot


def _headcount(event_data: EventData) -> int:
    return sum(1 + r.extra_people for r in event_data["attendees"])


def describe_responses_changes(current: dict[str, EventData], new: dict[str, EventData]) -> tuple[list[str], set[str]]:
    """Summarize what replacing `current` with `new` would change.

    Returns (lines, changed event names). Registrations missing from the new file
    are called out loudly: they usually mean someone signed up after the export.
    """
    empty = EventData(attendees=[], waitlist=[])
    lines: list[str] = []
    changed_events: set[str] = set()
    for event_name in sorted(set(current) | set(new)):
        before, after = current.get(event_name, empty), new.get(event_name, empty)
        old, updated = _snapshot(before), _snapshot(after)
        removed = [old[uid][1] for uid in old if uid not in updated]
        added = [updated[uid][1] for uid in updated if uid not in old]
        edited = [updated[uid][1] for uid in updated if uid in old and old[uid] != updated[uid]]
        order_changed = [e.user_id for e in before["attendees"]] != [e.user_id for e in after["attendees"]] or [
            e.user_id for e in before["waitlist"]
        ] != [e.user_id for e in after["waitlist"]]
        if not (removed or added or edited or order_changed):
            continue
        changed_events.add(event_name)
        lines.append(
            f"**{event_name}**: headcount {_headcount(before)} → {_headcount(after)}, "
            f"waitlist {len(before['waitlist'])} → {len(after['waitlist'])}"
        )
        if edited:
            lines.append(f"  ✏️ edited: {', '.join(edited)}")
        if added:
            lines.append(f"  ➕ added: {', '.join(added)}")
        if removed:
            lines.append(f"  ⚠️ REMOVED (not in uploaded file): {', '.join(removed)}")
        if order_changed and not (added or removed):
            lines.append("  ↕️ order changed")
    return lines, changed_events


def replace_responses(new: dict[str, EventData]) -> str | None:
    """Back up the current file, then replace all responses data. Returns the backup path, if one was written."""
    file_path = get_config()["RESPONSES_FILE"]
    backup_path = None
    if os.path.exists(file_path):
        backup_path = f"{file_path}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.pre-import.bak"
        shutil.copy2(file_path, backup_path)
    response_data.RESPONSE_DATA_CACHE = new
    save_responses()
    _log.warning("Responses data replaced by import (%d events). Backup: %s", len(new), backup_path)
    return backup_path
