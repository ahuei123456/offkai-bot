import { NextRequest, NextResponse } from 'next/server'
import { readEvents, readResponses, readCheckins, getDefaultEvent } from '../db'
import { verifyToken } from '../token'
import { MOCK_EVENTS, MOCK_ATTENDEES, mockCheckins, findMockAttendee } from '../mock'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const MOCK_MODE = process.env.MOCK_MODE === 'true'

export async function GET(request: NextRequest) {
  const rawToken = request.nextUrl.searchParams.get('token')
  if (!rawToken) return NextResponse.json({ error: 'missing_reference' }, { status: 400 })

  const resolved = verifyToken(rawToken)
  if (!resolved) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })

  if (MOCK_MODE) {
    // Event is the one the (v2) token is bound to, else the same default the
    // admin dashboard uses — never a divergent "active event" guess.
    const eventName = resolved.eventName || getDefaultEvent(MOCK_EVENTS)?.event_name
    if (!eventName || !MOCK_ATTENDEES[eventName]) {
      return NextResponse.json({ error: 'not_found' }, { status: 404 })
    }
    const mockA = findMockAttendee(eventName, resolved.userId)
    if (!mockA) return NextResponse.json({ error: 'not_found' }, { status: 404 })
    const ev = MOCK_EVENTS.find(e => e.event_name === eventName)!
    const isCheckedIn = mockCheckins.some(c => c.user_id === mockA.user_id && c.event_name === eventName)
    return NextResponse.json({
      attendee: {
        status: mockA.status,
        username: mockA.username,
        display_name: mockA.display_name || mockA.username,
        drinks: mockA.drinks,
        extra_people: mockA.extra_people,
        extras_names: mockA.extras_names,
        behavior_confirmed: true,
        arrival_confirmed: isCheckedIn,
      },
      event: ev,
    })
  }

  const events = readEvents()

  // Resolve the attendee's event: bound by the token (v2) or the shared default.
  let event
  if (resolved.eventName) {
    event = events.find(e => e.event_name === resolved.eventName && !e.archived)
  } else {
    event = getDefaultEvent(events)
  }
  if (!event) return NextResponse.json({ error: 'not_found' }, { status: 404 })

  const responses = readResponses()
  const eventResponses = responses[event.event_name]
  if (!eventResponses) {
    return NextResponse.json({ error: 'not_found' }, { status: 404 })
  }

  const uid = resolved.userId
  let attendee = (eventResponses.attendees || []).find(a => a.user_id === uid)
  let isWaitlist = false
  if (!attendee) {
    attendee = (eventResponses.waitlist || []).find(a => a.user_id === uid)
    if (attendee) isWaitlist = true
  }
  if (!attendee) {
    return NextResponse.json({ error: 'not_found' }, { status: 404 })
  }

  const checkins = readCheckins()
  const isCheckedIn = checkins.some(
    c => c.user_id === attendee!.user_id && c.event_name === event.event_name
  )

  return NextResponse.json({
    attendee: {
      status: isWaitlist ? 'waitlist' : 'attending',
      username: attendee.username,
      display_name: attendee.display_name || attendee.username,
      drinks: attendee.drinks || [],
      extra_people: attendee.extra_people || 0,
      extras_names: attendee.extras_names || [],
      behavior_confirmed: attendee.behavior_confirmed || false,
      arrival_confirmed: isCheckedIn || attendee.arrival_confirmed || false,
    },
    event: {
      event_name: event.event_name,
      venue: event.venue || 'TBA',
      address: event.address || '',
      google_maps_link: event.google_maps_link || '',
      event_datetime: event.event_datetime || '',
      event_deadline: event.event_deadline || '',
      open: event.open,
      drinks: event.drinks || [],
      max_capacity: event.max_capacity || 0,
    },
  })
}
