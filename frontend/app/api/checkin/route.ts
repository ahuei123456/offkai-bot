import { NextRequest, NextResponse } from 'next/server'
import { readEvents, readResponses, readCheckins, writeCheckins, getDefaultEvent } from '../db'
import type { CheckinRecord } from '../db'
import { verifyToken } from '../token'
import { parseEventParam, parseUserId } from '../validation'
import { MOCK_EVENTS, MOCK_ATTENDEES, mockCheckins, findMockAttendee } from '../mock'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

// ---------------------------------------------------------------------------
// Shared check-in / check-out mutations.
// QR scan and the manual "Check In" button both call checkInAttendee(); the
// manual "Check Out" button calls checkOutAttendee(). Both validate identically:
//   - the event exists and is not archived
//   - the attendee is registered (attending, not waitlist) for that event
//   - records are scoped by (user_id, event_name)
// ---------------------------------------------------------------------------

type CheckInOutcome =
  | { kind: 'checked_in'; record: CheckinRecord }
  | { kind: 'already_checked_in'; record: CheckinRecord }
  | { kind: 'event_not_found' }
  | { kind: 'event_archived' }
  | { kind: 'attendee_not_in_event' }
  | { kind: 'write_error' }

type CheckOutOutcome =
  | { kind: 'checked_out'; user_id: string; event_name: string }
  | { kind: 'event_not_found' }
  | { kind: 'event_archived' }
  | { kind: 'attendee_not_in_event' }
  | { kind: 'not_checked_in' }
  | { kind: 'write_error' }

// Resolves an *attending* attendee for an event (works in mock + real mode).
// Returns the display name, or an error kind.
function resolveAttendee(eventName: string, userId: string):
  | { ok: true; user_id: string; name: string }
  | { ok: false; kind: 'event_not_found' | 'event_archived' | 'attendee_not_in_event' } {
  if (MOCK_MODE) {
    const ev = MOCK_EVENTS.find(e => e.event_name === eventName)
    if (!ev || !MOCK_ATTENDEES[eventName]) return { ok: false, kind: 'event_not_found' }
    if (ev.archived) return { ok: false, kind: 'event_archived' }
    const a = findMockAttendee(eventName, userId)
    if (!a || a.status !== 'attending') return { ok: false, kind: 'attendee_not_in_event' }
    return { ok: true, user_id: a.user_id, name: a.display_name || a.username }
  }

  const ev = readEvents().find(e => e.event_name === eventName)
  if (!ev) return { ok: false, kind: 'event_not_found' }
  if (ev.archived) return { ok: false, kind: 'event_archived' }
  const er = readResponses()[eventName]
  const a = (er?.attendees || []).find(x => x.user_id === userId)
  if (!a) return { ok: false, kind: 'attendee_not_in_event' }
  return { ok: true, user_id: a.user_id, name: a.display_name || a.username }
}

function checkInAttendee(eventName: string, userId: string): CheckInOutcome {
  const found = resolveAttendee(eventName, userId)
  if (!found.ok) return { kind: found.kind }

  if (MOCK_MODE) {
    const existing = mockCheckins.find(c => c.user_id === found.user_id && c.event_name === eventName)
    if (existing) return { kind: 'already_checked_in', record: existing }
    const record: CheckinRecord = {
      user_id: found.user_id, event_name: eventName,
      checked_in_at: new Date().toISOString(), name: found.name,
    }
    mockCheckins.push(record)
    return { kind: 'checked_in', record }
  }

  const checkins = readCheckins()
  const existing = checkins.find(c => c.user_id === found.user_id && c.event_name === eventName)
  if (existing) return { kind: 'already_checked_in', record: existing }
  const record: CheckinRecord = {
    user_id: found.user_id, event_name: eventName,
    checked_in_at: new Date().toISOString(), name: found.name,
  }
  checkins.push(record)
  if (!writeCheckins(checkins)) return { kind: 'write_error' }
  return { kind: 'checked_in', record }
}

function checkOutAttendee(eventName: string, userId: string): CheckOutOutcome {
  // Same validation as check-in (owner request): event exists, not archived,
  // attendee belongs to the event.
  const found = resolveAttendee(eventName, userId)
  if (!found.ok) return { kind: found.kind }

  if (MOCK_MODE) {
    const idx = mockCheckins.findIndex(c => c.user_id === found.user_id && c.event_name === eventName)
    if (idx === -1) return { kind: 'not_checked_in' }
    mockCheckins.splice(idx, 1)
    return { kind: 'checked_out', user_id: found.user_id, event_name: eventName }
  }

  const checkins = readCheckins()
  const idx = checkins.findIndex(c => c.user_id === found.user_id && c.event_name === eventName)
  if (idx === -1) return { kind: 'not_checked_in' }
  checkins.splice(idx, 1)
  if (!writeCheckins(checkins)) return { kind: 'write_error' }
  return { kind: 'checked_out', user_id: found.user_id, event_name: eventName }
}

// Maps a check-in outcome to an HTTP response.
function checkInResponse(outcome: CheckInOutcome) {
  switch (outcome.kind) {
    case 'checked_in': return NextResponse.json({ record: outcome.record, already_checked_in: false })
    case 'already_checked_in': return NextResponse.json({ record: outcome.record, already_checked_in: true })
    case 'event_not_found': return NextResponse.json({ error: 'event_not_found' }, { status: 404 })
    case 'event_archived': return NextResponse.json({ error: 'event_archived' }, { status: 400 })
    case 'attendee_not_in_event': return NextResponse.json({ error: 'attendee_not_in_event' }, { status: 404 })
    case 'write_error': return NextResponse.json({ error: 'database_write_error' }, { status: 500 })
  }
}

function defaultEventName(): string | null {
  const src = MOCK_MODE ? MOCK_EVENTS : readEvents()
  return getDefaultEvent(src)?.event_name ?? null
}

// Shared check-out entry point used by both POST(action=checkout) and DELETE.
function performCheckout(rawUserId: unknown, rawBodyEvent: unknown, rawQueryEvent: string | null) {
  const userId = parseUserId(rawUserId)
  if (userId === null) return NextResponse.json({ error: 'invalid_user_id' }, { status: 400 })

  const bodyEvent = parseEventParam(rawBodyEvent)
  if (bodyEvent === false) return NextResponse.json({ error: 'invalid_event' }, { status: 400 })
  const queryEvent = parseEventParam(rawQueryEvent)
  if (queryEvent === false) return NextResponse.json({ error: 'invalid_event' }, { status: 400 })

  const eventName = bodyEvent || queryEvent || defaultEventName()
  if (!eventName) return NextResponse.json({ error: 'no_active_event' }, { status: 400 })

  const outcome = checkOutAttendee(eventName, userId)
  switch (outcome.kind) {
    case 'checked_out': return NextResponse.json({ removed: true, user_id: outcome.user_id, event_name: outcome.event_name })
    case 'event_not_found': return NextResponse.json({ error: 'event_not_found' }, { status: 404 })
    case 'event_archived': return NextResponse.json({ error: 'event_archived' }, { status: 400 })
    case 'attendee_not_in_event': return NextResponse.json({ error: 'attendee_not_in_event' }, { status: 404 })
    case 'not_checked_in': return NextResponse.json({ removed: false, error: 'not_checked_in' }, { status: 404 })
    case 'write_error': return NextResponse.json({ error: 'database_write_error' }, { status: 500 })
  }
}

// GET /api/checkin?key=<admin_key>&event=<event_name>
// Returns the check-ins for the selected event only (no cross-event leakage).
export async function GET(request: NextRequest) {
  const key = request.nextUrl.searchParams.get('key')
  if (!ADMIN_KEY || key !== ADMIN_KEY) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const requestedEvent = parseEventParam(request.nextUrl.searchParams.get('event'))
  if (requestedEvent === false) {
    return NextResponse.json({ error: 'invalid_event' }, { status: 400 })
  }
  const eventName = requestedEvent || defaultEventName()
  if (!eventName) return NextResponse.json([])

  const checkins = MOCK_MODE ? mockCheckins : readCheckins()
  return NextResponse.json(checkins.filter(c => c.event_name === eventName))
}

// POST /api/checkin?key=<admin_key>
//   QR check-in : { token, event_name? }  (event from token; event_name guards mismatch)
//   manual      : { user_id, event_name? }
//   manual out  : { action: 'checkout', user_id, event_name? }
export async function POST(request: NextRequest) {
  try {
    const key = request.nextUrl.searchParams.get('key')
    if (!ADMIN_KEY || key !== ADMIN_KEY) {
      return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
    }

    const body = await request.json().catch(() => ({}))

    const bodyEvent = parseEventParam(body?.event_name)
    if (bodyEvent === false) return NextResponse.json({ error: 'invalid_event' }, { status: 400 })
    const queryEvent = parseEventParam(request.nextUrl.searchParams.get('event'))
    if (queryEvent === false) return NextResponse.json({ error: 'invalid_event' }, { status: 400 })
    const selectedEvent = bodyEvent || queryEvent

    // Manual check-out routed over POST (some proxies reject DELETE).
    if (body?.action === 'checkout') {
      return performCheckout(body?.user_id, body?.event_name, request.nextUrl.searchParams.get('event'))
    }

    // Resolve user id + (optional) token-bound event.
    let userId: string
    let tokenEvent: string | null = null
    if (body?.user_id !== undefined && body?.user_id !== null) {
      // Manual admin check-in — already admin-key authenticated, no token needed.
      const parsed = parseUserId(body.user_id)
      if (parsed === null) return NextResponse.json({ error: 'invalid_user_id' }, { status: 400 })
      userId = parsed
    } else {
      const resolved = verifyToken(typeof body?.token === 'string' ? body.token : '')
      if (!resolved) return NextResponse.json({ error: 'invalid_token' }, { status: 401 })
      userId = resolved.userId
      tokenEvent = resolved.eventName
    }

    // Decide which event to check into.
    //  - v2 token: the token's event is authoritative. If the admin dropdown
    //    selected a different event, reject as wrong_event (the dropdown is only
    //    a mismatch guard — it never reassigns the QR's event).
    //  - manual / legacy token: use the selected event, else the shared default.
    let targetEvent: string | null
    if (tokenEvent) {
      if (selectedEvent && selectedEvent !== tokenEvent) {
        return NextResponse.json({ error: 'wrong_event', token_event: tokenEvent }, { status: 409 })
      }
      targetEvent = tokenEvent
    } else {
      targetEvent = selectedEvent || defaultEventName()
    }
    if (!targetEvent) return NextResponse.json({ error: 'no_active_event' }, { status: 400 })

    return checkInResponse(checkInAttendee(targetEvent, userId))
  } catch (e) {
    console.error('Error in checkin POST:', e)
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }
}

// DELETE /api/checkin?key=<admin_key>  body: { user_id, event_name? }
// Kept for API completeness; the UI uses POST(action=checkout) because some
// reverse proxies (openresty/NPM) reject the DELETE method.
export async function DELETE(request: NextRequest) {
  try {
    const key = request.nextUrl.searchParams.get('key')
    if (!ADMIN_KEY || key !== ADMIN_KEY) {
      return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
    }
    const body = await request.json().catch(() => ({}))
    return performCheckout(body?.user_id, body?.event_name, request.nextUrl.searchParams.get('event'))
  } catch (e) {
    console.error('Error in checkin DELETE:', e)
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }
}
