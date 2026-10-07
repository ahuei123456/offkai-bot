"""Private DM entry point into the frontend's existing proof uploader."""

import logging
import mimetypes
import os
import re
import unicodedata
from difflib import SequenceMatcher

import discord
from aiohttp import ClientSession, ClientTimeout, FormData

from offkai_bot.config import get_config
from offkai_bot.data.event import Event, load_event_data
from offkai_bot.data.response import get_responses, get_waitlist
from offkai_bot.util import build_checkin_token

_log = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PROOF_COMMAND = re.compile(r"^(?:payment\s+proof|proof\s+payment(?:\s+proof)?|i\s+paid)\b\s*(.*)$", re.I | re.S)


def registered_payment_events(user_id: int) -> list[Event]:
    return [
        event
        for event in load_event_data()
        if not event.archived
        and not event.interest_check
        and event.signup_form
        and event.signup_form.get("payment_methods")
        and any(
            entry.user_id == user_id for entry in [*get_responses(event.event_name), *get_waitlist(event.event_name)]
        )
    ]


def normalized_name(name: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", name).casefold() if char.isalnum())


def match_events(query: str, events: list[Event]) -> list[Event]:
    """Exact first, unique partial next; typos need a strong, separated match."""
    query = normalized_name(query)
    if not query:
        return []
    exact = [event for event in events if normalized_name(event.event_name) == query]
    if exact:
        return exact
    if len(query) < 3:
        return []
    partial = [event for event in events if query in normalized_name(event.event_name)]
    if partial:
        return partial
    if len(query) < 5:
        return []
    scores = sorted(
        [
            (SequenceMatcher(None, query, normalized_name(event.event_name)).ratio(), index, event)
            for index, event in enumerate(events)
            if re.findall(r"\d+", query) == re.findall(r"\d+", normalized_name(event.event_name))
        ],
        key=lambda item: item[0],
        reverse=True,
    )
    if not scores or scores[0][0] < 0.84:
        return []
    close = [event for score, _, event in scores if scores[0][0] - score < 0.12]
    return close


async def upload_attachment(attachment: discord.Attachment, event: Event, user_id: int) -> dict:
    settings = get_config()
    # A server-only URL may use Docker DNS while the public RSVP URL remains unchanged.
    url = os.environ.get("PROOF_UPLOAD_URL") or settings.get("FRONTEND_URL", "")
    key = settings.get("ADMIN_KEY", "")
    if not url or not key:
        raise RuntimeError("Proof uploader is not configured")
    mime = attachment.content_type or mimetypes.guess_type(attachment.filename)[0]
    if mime not in IMAGE_TYPES or attachment.size > MAX_IMAGE_BYTES:
        raise ValueError("Please upload a JPEG, PNG, WebP or GIF up to 10 MiB.")
    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        async with session.get(attachment.url) as download:
            download.raise_for_status()
            image = bytearray()
            async for chunk in download.content.iter_chunked(64 * 1024):
                image.extend(chunk)
                if len(image) > MAX_IMAGE_BYTES:
                    raise ValueError("Please upload a JPEG, PNG, WebP or GIF up to 10 MiB.")
        form = FormData()
        form.add_field("token", build_checkin_token(user_id, event.event_name, key))
        form.add_field("image", bytes(image), filename="proof", content_type=mime)
        async with session.post(f"{url.rstrip('/')}/api/payment-proof", data=form) as response:
            if response.status == 410:
                raise ValueError("Payment proof uploads for this event have expired.")
            if response.status == 413:
                raise ValueError("Please upload a JPEG, PNG, WebP or GIF up to 10 MiB.")
            if response.status == 400:
                error = await response.json()
                if isinstance(error, dict) and error.get("error") == "invalid_image":
                    raise ValueError("Please upload a JPEG, PNG, WebP or GIF up to 10 MiB.")
            response.raise_for_status()
            result = await response.json()
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("payment"), dict)
                or not isinstance(result["payment"].get("paid"), bool)
            ):
                raise RuntimeError("Unexpected proof response")
            return result


async def handle_payment_proof(message: discord.Message) -> bool:
    if message.guild is not None or message.author.bot:
        return False
    command = PROOF_COMMAND.fullmatch(message.content.strip())
    if not command:
        return False
    query = command.group(1).strip()
    if not query:
        await message.reply("Please include the event name: payment proof <event name>, with your screenshot attached.")
        return True
    matches = match_events(query, registered_payment_events(message.author.id))
    if not matches:
        await message.reply("I couldn't find a registered event matching that name. Please check the event name.")
    elif len(matches) > 1:
        names = "\n".join(f"• {event.event_name}" for event in matches[:10])
        await message.reply(f"Which event do you mean?\n{names}\nResend with the full event name and your screenshot.")
    elif not message.attachments:
        await message.reply("Please attach your payment screenshot.")
    elif len(message.attachments) != 1:
        await message.reply("Please attach one payment screenshot at a time.")
    else:
        event = matches[0]
        try:
            result = await upload_attachment(message.attachments[0], event, message.author.id)
            paid = result["payment"]["paid"]
            if not isinstance(paid, bool):
                raise RuntimeError("Unexpected proof response")
        except ValueError as error:
            await message.reply(str(error))
        except Exception:
            # Do not log CDN URLs, tokens or image contents.
            _log.warning("DM payment proof upload failed for event %r", event.event_name)
            await message.reply("Couldn't confirm your payment proof upload. Check your RSVP page or try again.")
        else:
            action = "updated" if result.get("replaced") else "received"
            status = "Your payment remains confirmed." if paid else "Awaiting confirmation."
            await message.reply(f"Payment proof {action} for {event.event_name}. {status}")
    return True
