import { NextRequest, NextResponse } from 'next/server'
import { readEvents, readResponses, getActiveEvent } from '../db'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

const MOCK_EVENT_NAME = 'Bandori 10th Offkai'
const MOCK_ATTENDEES = [
  { user_id: 123, username: 'fadekyun', display_name: 'Fadekyun', drinks: ['Highball (L)'], extra_people: 1, extras_names: ['Senpai'], status: 'attending' },
  { user_id: 124, username: 'sakichan', display_name: 'Sakichan', drinks: ['Oolong Tea (L)', 'Cream Soda (L)'], extra_people: 0, extras_names: [], status: 'attending' },
  { user_id: 125, username: 'hoshino', display_name: 'Hoshino', drinks: ['Sapporo Beer (L)'], extra_people: 2, extras_names: ['Friend A', 'Friend B'], status: 'attending' },
  { user_id: 126, username: 'arisa', display_name: 'Arisa', drinks: ['Fresh Lemon Sour (L)'], extra_people: 0, extras_names: [], status: 'waitlist' },
]

export async function GET(request: NextRequest) {
  const key = request.nextUrl.searchParams.get('key')
  if (!ADMIN_KEY || key !== ADMIN_KEY) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  if (MOCK_MODE) {
    return NextResponse.json({ event_name: MOCK_EVENT_NAME, attendees: MOCK_ATTENDEES })
  }

  const events = readEvents()
  const activeEvent = getActiveEvent(events)
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
