import { NextRequest, NextResponse } from 'next/server'
import crypto from 'crypto'
import { readEvents, readResponses, readCheckins, getActiveEvent } from '../db'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

const MOCK_EVENT = {
  event_name: 'Bandori 10th Offkai',
  venue: 'TBD',
  address: 'Tokyo, Japan',
  google_maps_link: '',
  event_datetime: '2026-06-14T12:00:00+09:00',
  event_deadline: '2026-06-12T00:00:00+09:00',
  open: true,
  drinks: ['Oolong Tea (L)', 'Cream Soda (L)', 'Coca-Cola (L)', 'Sapporo Beer (L)', 'Highball (L)', 'Fresh Lemon Sour (L)'],
  max_capacity: 30,
}

const MOCK_ATTENDEE = {
  status: 'attending',
  username: 'fadekyun',
  display_name: 'Fadekyun',
  drinks: ['Highball (L)'],
  extra_people: 1,
  extras_names: ['Senpai'],
  behavior_confirmed: true,
  arrival_confirmed: false,
}

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get('token')
  if (!token) return NextResponse.json({ error: 'missing_reference' }, { status: 400 })

  if (MOCK_MODE) {
    return NextResponse.json({
      attendee: { ...MOCK_ATTENDEE, reference: token },
      event: MOCK_EVENT,
    })
  }

  const events = readEvents()
  const activeEvent = getActiveEvent(events)
  if (!activeEvent) {
    return NextResponse.json({ error: 'not_found' }, { status: 404 })
  }

  const responses = readResponses()
  const eventResponses = responses[activeEvent.event_name]
  if (!eventResponses) {
    return NextResponse.json({ error: 'not_found' }, { status: 404 })
  }

  // Look for attendee in attendees list or waitlist list matching user_id or username
  let cleanedToken = token.trim().toLowerCase()

  if (ADMIN_KEY) {
    if (cleanedToken.includes('.')) {
      const [id, sig] = cleanedToken.split('.')
      const expectedSig = crypto.createHmac('sha256', ADMIN_KEY).update(id).digest('hex').substring(0, 16)
      if (sig === expectedSig) {
        cleanedToken = id.toLowerCase()
      } else {
        return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
      }
    } else {
      // In production (when ADMIN_KEY is configured), do not allow raw guessable tokens!
      return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
    }
  }

  let attendee = (eventResponses.attendees || []).find(
    a => a.user_id.toString() === cleanedToken || a.username.toLowerCase() === cleanedToken
  )
  let isWaitlist = false

  if (!attendee) {
    attendee = (eventResponses.waitlist || []).find(
      a => a.user_id.toString() === cleanedToken || a.username.toLowerCase() === cleanedToken
    )
    if (attendee) {
      isWaitlist = true
    }
  }

  if (!attendee) {
    return NextResponse.json({ error: 'not_found' }, { status: 404 })
  }

  // Load checkins to see if they checked in on the frontend
  const checkins = readCheckins()
  const isCheckedIn = checkins.some(
    c => c.user_id === attendee!.user_id && c.event_name === activeEvent.event_name
  )

  const attendeeData = {
    status: isWaitlist ? 'waitlist' : 'attending',
    username: attendee.username,
    display_name: attendee.display_name || attendee.username,
    drinks: attendee.drinks || [],
    extra_people: attendee.extra_people || 0,
    extras_names: attendee.extras_names || [],
    behavior_confirmed: attendee.behavior_confirmed || false,
    arrival_confirmed: isCheckedIn || attendee.arrival_confirmed || false,
  }

  const eventData = {
    event_name: activeEvent.event_name,
    venue: activeEvent.venue || 'TBA',
    address: activeEvent.address || '',
    google_maps_link: activeEvent.google_maps_link || '',
    event_datetime: activeEvent.event_datetime || '',
    event_deadline: activeEvent.event_deadline || '',
    open: activeEvent.open,
    drinks: activeEvent.drinks || [],
    max_capacity: activeEvent.max_capacity || 0,
  }

  return NextResponse.json({
    attendee: attendeeData,
    event: eventData
  })
}
