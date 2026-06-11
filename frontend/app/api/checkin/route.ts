import { NextRequest, NextResponse } from 'next/server'
import crypto from 'crypto'
import { readEvents, readResponses, readCheckins, writeCheckins, getDefaultEvent } from '../db'
import type { CheckinRecord } from '../db'
import { MOCK_EVENTS, MOCK_ATTENDEES, mockCheckins, findMockAttendee } from '../mock'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

const MAX_EVENT_NAME_LEN = 200
const MAX_TOKEN_LEN = 2048

function parseEventParam(raw: string | null): string | null | false {
  if (raw === null) return null
  if (typeof raw !== 'string' || raw.length > MAX_EVENT_NAME_LEN) return false
  const trimmed = raw.trim()
  if (!trimmed) return false
  return trimmed
}

// Resolves a scanned token to a numeric user_id.
// When ADMIN_KEY is set, the token MUST be a valid `<id>.<sig>` HMAC pair —
// raw guessable ids are rejected. Returns the id string or null on failure.
function resolveTokenUserId(token: string): string | null {
  const cleaned = token.trim().toLowerCase()

  if (ADMIN_KEY) {
    if (!cleaned.includes('.')) return null
    const [id, sig] = cleaned.split('.')
    if (!id || !sig) return null
    const expectedSig = crypto.createHmac('sha256', ADMIN_KEY).update(id).digest('hex').substring(0, 16)
    if (sig !== expectedSig) return null
    return id.toLowerCase()
  }

  return cleaned
}

// GET /api/checkin?key=<admin_key>&event=<event_name>
// Returns the check-ins for the selected event only (so historical check-ins
// never leak into another event's view — issue #77).
export async function GET(request: NextRequest) {
  const key = request.nextUrl.searchParams.get('key')
  if (!ADMIN_KEY || key !== ADMIN_KEY) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const requestedEvent = parseEventParam(request.nextUrl.searchParams.get('event'))
  if (requestedEvent === false) {
    return NextResponse.json({ error: 'invalid_event' }, { status: 400 })
  }

  if (MOCK_MODE) {
    const defaultEvent = getDefaultEvent(MOCK_EVENTS)
    const eventName = requestedEvent || defaultEvent?.event_name
    return NextResponse.json(mockCheckins.filter(c => c.event_name === eventName))
  }

  const checkins = readCheckins()

  // Scope to the requested event, else the default event.
  let eventName = requestedEvent
  if (!eventName) {
    eventName = getDefaultEvent(readEvents())?.event_name ?? null
  }
  if (!eventName) return NextResponse.json([])

  return NextResponse.json(checkins.filter(c => c.event_name === eventName))
}

// POST /api/checkin?key=<admin_key>  body: { token, event_name? }
// Checks the scanned attendee into the selected event. The attendee must be
// registered (attending) for THAT event — otherwise the scan is rejected rather
// than silently checking them into the wrong event (issue #77 / #76).
export async function POST(request: NextRequest) {
  try {
    const key = request.nextUrl.searchParams.get('key')
    if (!ADMIN_KEY || key !== ADMIN_KEY) {
      return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
    }

    const body = await request.json().catch(() => ({}))
    const token: unknown = body?.token
    if (typeof token !== 'string' || !token || token.length > MAX_TOKEN_LEN) {
      return NextResponse.json({ error: 'missing_token' }, { status: 400 })
    }

    // Event can come from the body or the query string; both validated.
    const bodyEvent = parseEventParam(typeof body?.event_name === 'string' ? body.event_name : null)
    if (bodyEvent === false) {
      return NextResponse.json({ error: 'invalid_event' }, { status: 400 })
    }
    const queryEvent = parseEventParam(request.nextUrl.searchParams.get('event'))
    if (queryEvent === false) {
      return NextResponse.json({ error: 'invalid_event' }, { status: 400 })
    }
    const requestedEvent = bodyEvent || queryEvent

    const userId = resolveTokenUserId(token)
    if (userId === null) {
      return NextResponse.json({ error: 'invalid_token' }, { status: 401 })
    }

    if (MOCK_MODE) {
      const defaultEvent = getDefaultEvent(MOCK_EVENTS)
      const eventName = requestedEvent || defaultEvent?.event_name
      if (!eventName || !MOCK_ATTENDEES[eventName]) {
        return NextResponse.json({ error: 'event_not_found' }, { status: 404 })
      }

      const attendee = findMockAttendee(eventName, Number(userId))
      if (!attendee || attendee.status !== 'attending') {
        return NextResponse.json({ error: 'attendee_not_in_event' }, { status: 404 })
      }

      const existing = mockCheckins.find(c => c.user_id === attendee.user_id && c.event_name === eventName)
      if (existing) {
        return NextResponse.json({ record: existing, already_checked_in: true })
      }

      const record: CheckinRecord = {
        user_id: attendee.user_id,
        event_name: eventName,
        checked_in_at: new Date().toISOString(),
        name: attendee.display_name || attendee.username,
      }
      mockCheckins.push(record)
      return NextResponse.json({ record, already_checked_in: false })
    }

    const events = readEvents()

    // Resolve the target event (validated selection, else default).
    let targetEvent
    if (requestedEvent) {
      targetEvent = events.find(e => e.event_name === requestedEvent && !e.archived)
      if (!targetEvent) {
        return NextResponse.json({ error: 'event_not_found' }, { status: 404 })
      }
    } else {
      targetEvent = getDefaultEvent(events)
    }
    if (!targetEvent) {
      return NextResponse.json({ error: 'no_active_event' }, { status: 400 })
    }

    const responses = readResponses()
    const eventResponses = responses[targetEvent.event_name]
    if (!eventResponses) {
      return NextResponse.json({ error: 'no_responses_for_event' }, { status: 400 })
    }

    // Attendee must be in the *attending* list for the selected event.
    const attendee = (eventResponses.attendees || []).find(
      a => a.user_id.toString() === userId || a.username.toLowerCase() === userId
    )
    if (!attendee) {
      return NextResponse.json({ error: 'attendee_not_in_event' }, { status: 404 })
    }

    const checkins = readCheckins()
    const existingIndex = checkins.findIndex(
      c => c.user_id === attendee.user_id && c.event_name === targetEvent.event_name
    )

    if (existingIndex !== -1) {
      return NextResponse.json({
        record: checkins[existingIndex],
        already_checked_in: true
      })
    }

    const newRecord: CheckinRecord = {
      user_id: attendee.user_id,
      event_name: targetEvent.event_name,
      checked_in_at: new Date().toISOString(),
      name: attendee.display_name || attendee.username
    }

    checkins.push(newRecord)
    const success = writeCheckins(checkins)
    if (!success) {
      return NextResponse.json({ error: 'database_write_error' }, { status: 500 })
    }

    return NextResponse.json({
      record: newRecord,
      already_checked_in: false
    })
  } catch (e) {
    console.error('Error in checkin POST:', e)
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }
}
