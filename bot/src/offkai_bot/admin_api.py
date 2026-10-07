"""Private frontend-to-bot actions; never publish this port on the Docker host."""

import hmac
import logging
import os
import re

import discord
from aiohttp import web

from offkai_bot.config import get_config
from offkai_bot.data.event import get_event
from offkai_bot.errors import EventNotFoundError, ResponseNotFoundError, ThreadAccessError, ThreadNotFoundError
from offkai_bot.event_actions import fetch_thread_for_event
from offkai_bot.payment_proof import registered_payment_events
from offkai_bot.registration_removal import remove_registration

_log = logging.getLogger(__name__)


async def parse_admin_request(request: web.Request, client: discord.Client) -> tuple[str, str] | web.Response:
    key = get_config().get("ADMIN_KEY", "")
    if not key or not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {key}"):
        return web.json_response({"error": "unauthorized"}, status=401)
    if not client.is_ready():
        return web.json_response({"error": "bot_unavailable"}, status=503)
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return web.json_response({"error": "invalid_request"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_request"}, status=400)
    event_name, user_id = body.get("event_name"), body.get("user_id")
    if not isinstance(user_id, str) or not re.fullmatch(r"[0-9]{16,22}", user_id):
        return web.json_response({"error": "invalid_request"}, status=400)
    if not isinstance(event_name, str) or not event_name or len(event_name) > 100:
        return web.json_response({"error": "invalid_request"}, status=400)
    return event_name, user_id


def create_admin_app(client: discord.Client) -> web.Application:
    async def confirm_payment(request: web.Request) -> web.Response:
        parsed = await parse_admin_request(request, client)
        if isinstance(parsed, web.Response):
            return parsed
        event_name, user_id = parsed
        if not any(event.event_name == event_name for event in registered_payment_events(int(user_id))):
            return web.json_response({"error": "not_found"}, status=404)
        try:
            user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
            await user.send(f"Payment confirmed for {event_name}!")
        except discord.HTTPException:
            return web.json_response({"error": "dm_failed"}, status=502)
        return web.json_response({"sent": True})

    async def remove(request: web.Request) -> web.Response:
        parsed = await parse_admin_request(request, client)
        if isinstance(parsed, web.Response):
            return parsed
        event_name, user_id = parsed
        settings = get_config()
        try:
            event = get_event(event_name)
            if event.archived or event.interest_check:
                return web.json_response({"error": "event_unavailable"}, status=400)
            # Resolve the real guild/thread before changing registration data.
            thread = await fetch_thread_for_event(client, event)
            if thread.guild.id not in settings["GUILDS"]:
                return web.json_response({"error": "event_unavailable"}, status=403)
            user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
        except (EventNotFoundError, ThreadNotFoundError, discord.NotFound):
            return web.json_response({"error": "preflight_not_found", "removed": False}, status=404)
        except (ThreadAccessError, discord.Forbidden):
            return web.json_response({"error": "preflight_forbidden", "removed": False}, status=403)
        except Exception:
            _log.exception("Registration removal preflight failed")
            return web.json_response({"error": "preflight_unavailable", "removed": False}, status=503)
        try:
            result = await remove_registration(client, event, user, thread.guild, allow_waitlist=True, thread=thread)
        except (EventNotFoundError, ResponseNotFoundError):
            return web.json_response({"error": "not_found"}, status=404)
        except Exception:
            _log.exception("Admin registration removal failed for event %r", event_name)
            return web.json_response({"error": "removal_failed"}, status=502)
        try:
            await user.send(
                f"👋 Your attendance for **{event_name}** has been withdrawn by the organizer.\n"
                f"👋 主催者により**{event_name}**への参加が取り消されました。"
            )
        except discord.HTTPException:
            result["warnings"].append("The registration was removed, but the confirmation DM could not be delivered.")
        return web.json_response(result)

    app = web.Application(client_max_size=4096)
    app.router.add_post("/registrations/remove", remove)
    app.router.add_post("/payments/confirm", confirm_payment)
    return app


async def start_admin_api(client: discord.Client) -> web.AppRunner | None:
    port = int(os.environ.get("ADMIN_API_PORT", "0"))
    if not port:
        return None
    runner = web.AppRunner(create_admin_app(client), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, os.environ.get("ADMIN_API_HOST", "127.0.0.1"), port).start()
    except Exception:
        await runner.cleanup()
        raise
    return runner
