import { NextRequest, NextResponse } from 'next/server'
import { readEvents, getDefaultEvent, orderEventsForDropdown } from '../db'
import { MOCK_EVENTS } from '../mock'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

// GET /api/events?key=<admin_key>
// Returns the selectable (non-archived) events for the admin dropdown, ordered
// nearest-upcoming-first then most-recent-past, plus the default selection
// (next upcoming event by JST date).
export async function GET(request: NextRequest) {
  const key = request.nextUrl.searchParams.get('key')
  if (!ADMIN_KEY || key !== ADMIN_KEY) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const source = MOCK_MODE ? MOCK_EVENTS : readEvents()
  const ordered = orderEventsForDropdown(source)
  const defaultEvent = getDefaultEvent(source)

  const events = ordered.map(e => ({
    event_name: e.event_name,
    event_datetime: e.event_datetime ?? null,
    open: e.open,
  }))

  return NextResponse.json({
    events,
    default_event_name: defaultEvent?.event_name ?? null,
  })
}
