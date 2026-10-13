"""Flag signups whose form answers may belong to another user (read-only).

Before the fix on branch fix/modal-custom-id-collision, every signup modal for an
event shared one custom_id. With the payment / no-show step (added in #138), a
second user's submission could overwrite the first user's pending answers, so the
first user was recorded under their own Discord account but with the other user's
preferred name, guests, drinks and payment method. User ID, username and queue
order are always correct.

When this happens both users end up with identical answers, so this script looks
for answers shared across different users. It cannot detect a victim whose
overwriter left the name blank and brought no guests or drinks; in that case only
the payment method may be wrong.

Usage (stdlib only, never writes):
    uv run python bot/scripts/find_mixed_signups.py data/responses.json
    uv run python bot/scripts/find_mixed_signups.py data/responses.json --event "Event Name"
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def went_through_payment_step(entry: dict) -> bool:
    """Only the two-step payment flow re-read the shared modal, so only these entries can be affected."""
    return bool(entry.get("payment_method")) or entry.get("no_show_agreed") is True


def norm(value: object) -> str:
    return str(value or "").strip().casefold()


def describe(entry: dict, status: str) -> str:
    extras = ", ".join(entry.get("extras_names") or []) or "-"
    drinks = ", ".join(entry.get("drinks") or []) or "-"
    return (
        f"  [{status}] user_id={entry.get('user_id')} username={entry.get('username')!r} "
        f"recorded_name={entry.get('display_name')!r} guests={entry.get('extra_people', 0)} ({extras}) "
        f"drinks={drinks} payment={entry.get('payment_method')!r} at={entry.get('timestamp')}"
    )


def check_event(entries: list[tuple[str, dict]]) -> dict[int, tuple[str, dict, set[str]]]:
    """Return {user_id: (status, entry, reasons)} for suspicious entries in one event."""
    candidates = [(status, e) for status, e in entries if went_through_payment_step(e)]
    flagged: dict[int, tuple[str, dict, set[str]]] = {}

    def flag(status: str, entry: dict, reason: str) -> None:
        uid = int(entry.get("user_id", 0))
        flagged.setdefault(uid, (status, entry, set()))[2].add(reason)

    # 1. Same full answer set on different users: the strongest signal.
    by_answers: dict[tuple, list[tuple[str, dict]]] = defaultdict(list)
    # 2. Same recorded name on different users.
    by_name: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    # 3. Same (non-empty) guest names on different users.
    by_extras: dict[tuple[str, ...], list[tuple[str, dict]]] = defaultdict(list)
    for status, e in candidates:
        extras = tuple(sorted(norm(n) for n in e.get("extras_names") or []))
        drinks = tuple(sorted(norm(d) for d in e.get("drinks") or []))
        by_answers[(norm(e.get("display_name")), e.get("extra_people", 0), extras, drinks)].append((status, e))
        if norm(e.get("display_name")):
            by_name[norm(e.get("display_name"))].append((status, e))
        if extras:
            by_extras[extras].append((status, e))

    for group, reason in [
        *((g, "identical answers to another user") for g in by_answers.values()),
        *((g, "same recorded name as another user") for g in by_name.values()),
        *((g, "same guest names as another user") for g in by_extras.values()),
    ]:
        if len({int(e.get("user_id", 0)) for _, e in group}) > 1:
            for status, e in group:
                flag(status, e, reason)

    # 4. Recorded name is exactly another registrant's username.
    usernames = {norm(e.get("username")): int(e.get("user_id", 0)) for _, e in entries}
    for status, e in candidates:
        owner = usernames.get(norm(e.get("display_name")))
        if owner is not None and owner != int(e.get("user_id", 0)):
            flag(status, e, "recorded name is another registrant's username")

    return flagged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("responses_file", type=Path, help="Path to the bot's responses JSON file.")
    parser.add_argument("--event", help="Only check this event.")
    args = parser.parse_args()

    data = json.loads(args.responses_file.read_text(encoding="utf-8"))
    total = 0
    for event_name, event_data in data.items():
        if args.event and event_name != args.event:
            continue
        if not isinstance(event_data, dict):
            continue
        entries = [("attendee", e) for e in event_data.get("attendees", [])] + [
            ("waitlist", e) for e in event_data.get("waitlist", [])
        ]
        checked = sum(went_through_payment_step(e) for _, e in entries)
        if not checked:
            continue
        flagged = check_event(entries)
        print(f"\n=== {event_name}: {checked} payment-flow signup(s) checked, {len(flagged)} flagged ===")
        for status, entry, reasons in sorted(flagged.values(), key=lambda f: str(f[1].get("timestamp"))):
            print(describe(entry, status))
            print(f"    why: {'; '.join(sorted(reasons))}")
        total += len(flagged)

    print(f"\n{total} signup(s) flagged. Confirm each flagged user's name, guests, drinks and payment method.")
    print("Flagged pairs share answers: usually one of them is correct and the other was overwritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
