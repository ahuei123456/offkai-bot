import { NextRequest, NextResponse } from 'next/server'
import { readEvents, readResponses, readCheckins, writeCheckins, getActiveEvent } from '../db'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

// GET /api/checkin?key=<admin_key> — returns list of checkins
export async function GET(request: NextRequest) {
  const key = request.nextUrl.searchParams.get('key')
  if (!ADMIN_KEY || key !== ADMIN_KEY) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  if (MOCK_MODE) {
    return NextResponse.json([
      { user_id: 123, event_name: 'Bandori 10th Offkai', checked_in_at: new Date().toISOString(), name: 'Fadekyun' }
    ])
  }

  const checkins = readCheckins()
  return NextResponse.json(checkins)
}

// POST /api/checkin — registers a checkin { token }
export async function POST(request: NextRequest) {
  try {
    const key = request.nextUrl.searchParams.get('key')
    if (!ADMIN_KEY || key !== ADMIN_KEY) {
      return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
    }

    const body = await request.json()
    const { token } = body
    if (!token) {
      return NextResponse.json({ error: 'missing_token' }, { status: 400 })
    }

    if (MOCK_MODE) {
      return NextResponse.json({
        record: {
          user_id: 123,
          event_name: 'Bandori 10th Offkai',
          checked_in_at: new Date().toISOString(),
          name: 'Fadekyun'
        },
        already_checked_in: false
      })
    }

    const events = readEvents()
    const activeEvent = getActiveEvent(events)
    if (!activeEvent) {
      return NextResponse.json({ error: 'no_active_event' }, { status: 400 })
    }

    const responses = readResponses()
    const eventResponses = responses[activeEvent.event_name]
    if (!eventResponses) {
      return NextResponse.json({ error: 'no_responses_for_event' }, { status: 400 })
    }

    // Only allow checking in attendees (not waitlist)
    const cleanedToken = token.trim().toLowerCase()
    const attendee = (eventResponses.attendees || []).find(
      a => a.user_id.toString() === cleanedToken || a.username.toLowerCase() === cleanedToken
    )

    if (!attendee) {
      return NextResponse.json({ error: 'attendee_not_found_or_not_attending' }, { status: 404 })
    }

    const checkins = readCheckins()
    const existingIndex = checkins.findIndex(
      c => c.user_id === attendee.user_id && c.event_name === activeEvent.event_name
    )

    if (existingIndex !== -1) {
      return NextResponse.json({
        record: checkins[existingIndex],
        already_checked_in: true
      })
    }

    const newRecord = {
      user_id: attendee.user_id,
      event_name: activeEvent.event_name,
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
