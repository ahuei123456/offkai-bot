# src/offkai_bot/data/responses_transfer.py
"""Export the raw responses data and import an edited copy (for organizers without server access)."""

import hashlib
import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass
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

# Export metadata key. It records a fingerprint of every event as exported, so an
# import only touches the events the organizer edited and refuses to overwrite an
# event that changed in the bot after the export (e.g. a new sign-up).
EXPORT_META_KEY = "_export"


@dataclass
class ResponsesImport:
    events: dict[str, EventData]
    baseline: dict[str, str]  # event name -> fingerprint at export time


def _empty() -> EventData:
    return EventData(attendees=[], waitlist=[])


def event_fingerprint(event_data: EventData) -> str:
    canonical = json.dumps(
        {"attendees": event_data["attendees"], "waitlist": event_data["waitlist"]},
        cls=DataclassJSONEncoder,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def export_responses_json(
    data: dict[str, EventData] | None = None, baseline: dict[str, EventData] | None = None
) -> bytes:
    """Serialize responses data (default: current) with fingerprints of `baseline` (default: the same data).

    Passing a different baseline produces a file that, when imported, turns `baseline` back into `data`.
    """
    data = load_responses() if data is None else data
    baseline = data if baseline is None else baseline
    meta = {
        "exported_at": datetime.now(UTC).isoformat(),
        "event_fingerprints": {name: event_fingerprint(event_data) for name, event_data in baseline.items()},
    }
    payload = {EXPORT_META_KEY: meta, **data}
    return json.dumps(payload, indent=4, cls=DataclassJSONEncoder, ensure_ascii=False).encode("utf-8")


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
    # The entry's own event_name drives its RSVP link, so it must match the event it is filed under.
    if entry.get("event_name", event_name) != event_name:
        raise ResponsesImportError(f"{where} has event_name {entry['event_name']!r}; it must be '{event_name}'.")
    extra_people = entry.get("extra_people", 0)
    if not isinstance(extra_people, int) or not 0 <= extra_people <= MAX_EXTRA_PEOPLE:
        raise ResponsesImportError(f"{where} has extra_people {extra_people!r}; it must be 0-{MAX_EXTRA_PEOPLE}.")
    extras_names = entry.get("extras_names", [])
    # Older registrations predate extras names, so an empty list is still accepted.
    if not isinstance(extras_names, list) or (extras_names and len(extras_names) != extra_people):
        raise ResponsesImportError(f"{where} needs exactly {extra_people} extras_names to match extra_people.")
    return entry


def _parse_baseline(meta: object) -> dict[str, str]:
    fingerprints = cast(dict[str, Any], meta).get("event_fingerprints") if isinstance(meta, dict) else None
    if not isinstance(fingerprints, dict) or not all(isinstance(v, str) for v in fingerprints.values()):
        raise ResponsesImportError(
            f"The file has no valid '{EXPORT_META_KEY}' section. Export a fresh copy with /export_responses, "
            "redo your edits in it and upload that."
        )
    return cast(dict[str, str], fingerprints)


def parse_responses_import(raw: bytes) -> ResponsesImport:
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
    baseline = _parse_baseline(data.pop(EXPORT_META_KEY, None))

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
    return ResponsesImport(events=parsed, baseline=baseline)


def merge_responses_import(current: dict[str, EventData], upload: ResponsesImport) -> dict[str, EventData]:
    """Return `current` with the organizer's edits from `upload` applied.

    An event counts as edited when the upload differs from its export-time
    fingerprint. Unedited events keep their current data, so registrations made
    after the export survive. An edited event that also changed in the bot since
    the export is a conflict and rejects the whole import.
    """
    empty_fingerprint = event_fingerprint(_empty())
    merged = dict(current)
    conflicts: list[str] = []
    for event_name in sorted(set(current) | set(upload.events) | set(upload.baseline)):
        uploaded = upload.events.get(event_name, _empty())
        exported = upload.baseline.get(event_name, empty_fingerprint)
        uploaded_fingerprint = event_fingerprint(uploaded)
        if uploaded_fingerprint == exported:
            continue  # Not edited by the organizer.
        current_fingerprint = event_fingerprint(current.get(event_name, _empty()))
        if current_fingerprint == uploaded_fingerprint:
            continue  # The bot already has this data.
        if current_fingerprint != exported:
            conflicts.append(event_name)
            continue
        merged[event_name] = uploaded
    if conflicts:
        raise ResponsesImportError(
            f"Registrations changed in the bot after your export for: {', '.join(conflicts)}. "
            "Export again with /export_responses, redo your edits for these events and upload the new file."
        )
    return merged


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

    Returns (lines, changed event names). Removed registrations are called out loudly.
    """
    empty = _empty()
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
            lines.append(f"  ⚠️ REMOVED: {', '.join(removed)}")
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
    save_responses(new)
    response_data.RESPONSE_DATA_CACHE = new
    _log.warning("Responses data replaced by import (%d events). Backup: %s", len(new), backup_path)
    return backup_path
