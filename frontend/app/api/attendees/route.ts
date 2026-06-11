import { NextRequest, NextResponse } from 'next/server'
import { readEvents, readResponses, getDefaultEvent } from '../db'
import { MOCK_EVENTS, MOCK_ATTENDEES } from '../mock'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

const MAX_EVENT_NAME_LEN = 200

// Validates the optional ?event= query param. Returns the trimmed string,
// `null` when absent, or `false` when malformed.
function parseEventParam(raw: string | null): string | null | false {
  if (raw === null) return null
  if (typeof raw !== 'string' || raw.length > MAX_EVENT_NAME_LEN) return false
  const trimmed = raw.trim()
  if (!trimmed) return false
  return trimmed
}

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
    if (!eventName) {
      return NextResponse.json({ event_name: 'No Active Event', attendees: [] })
    }
    if (!MOCK_ATTENDEES[eventName]) {
      return NextResponse.json({ error: 'event_not_found' }, { status: 404 })
    }
    return NextResponse.json({ event_name: eventName, attendees: MOCK_ATTENDEES[eventName] })
  }

  const events = readEvents()

  // Resolve which event to show: an explicit (validated) selection, else default.
  let activeEvent
  if (requestedEvent) {
    activeEvent = events.find(e => e.event_name === requestedEvent && !e.archived)
    if (!activeEvent) {
      return NextResponse.json({ error: 'event_not_found' }, { status: 404 })
    }
  } else {
    activeEvent = getDefaultEvent(events)
  }

  if (!activeEvent) {
    return NextResponse.json({ event_name: 'No Active Event', attendees: [] })
  }

  const responses = readResponses()
  const eventResponses = responses[activeEvent.event_name]

  if (!eventResponses) {
    return NextResponse.json({ event_name: activeEvent.event_name, attendees: [] })
  }

  const attendeesList = (eventResponses.attendees || []).map(a => ({
    user_id: a.user_id,
    username: a.username,
    display_name: a.display_name,
    drinks: a.drinks || [],
    extra_people: a.extra_people || 0,
    extras_names: a.extras_names || [],
    status: 'attending' as const
  }))

  const waitlistList = (eventResponses.waitlist || []).map(a => ({
    user_id: a.user_id,
    username: a.username,
    display_name: a.display_name,
    drinks: a.drinks || [],
    extra_people: a.extra_people || 0,
    extras_names: a.extras_names || [],
    status: 'waitlist' as const
  }))

  const combined = [...attendeesList, ...waitlistList]

  return NextResponse.json({
    event_name: activeEvent.event_name,
    attendees: combined
  })
}
