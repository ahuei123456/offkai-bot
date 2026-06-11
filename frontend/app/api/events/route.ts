import { NextRequest, NextResponse } from 'next/server'
import { readEvents, getDefaultEvent } from '../db'
import { MOCK_EVENTS } from '../mock'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const MOCK_MODE = process.env.MOCK_MODE === 'true'
const ADMIN_KEY = process.env.ADMIN_KEY ?? ''

// GET /api/events?key=<admin_key>
// Returns the selectable (non-archived) events for the admin dropdown plus the
// name of the event that should be selected by default (next upcoming).
export async function GET(request: NextRequest) {
  const key = request.nextUrl.searchParams.get('key')
  if (!ADMIN_KEY || key !== ADMIN_KEY) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const source = MOCK_MODE ? MOCK_EVENTS : readEvents()
  const selectable = source.filter(e => !e.archived)

  // Newest first so upcoming events sit at the top of the dropdown.
  const sorted = [...selectable].sort((a, b) => {
    const ta = a.event_datetime ? new Date(a.event_datetime).getTime() : 0
    const tb = b.event_datetime ? new Date(b.event_datetime).getTime() : 0
    return tb - ta
  })

  const defaultEvent = getDefaultEvent(selectable)

  const events = sorted.map(e => ({
    event_name: e.event_name,
    event_datetime: e.event_datetime ?? null,
    open: e.open,
  }))

  return NextResponse.json({
    events,
    default_event_name: defaultEvent?.event_name ?? null,
  })
}
