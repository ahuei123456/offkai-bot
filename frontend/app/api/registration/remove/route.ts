import { NextRequest, NextResponse } from 'next/server'
import { parseEventParam, parseUserId } from '../../validation'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: NextRequest) {
  const key = process.env.ADMIN_KEY
  if (!key || request.nextUrl.searchParams.get('key') !== key) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }
  const body = await request.json().catch(() => null)
  const eventName = parseEventParam(body?.event_name)
  const userId = typeof body?.user_id === 'string' ? parseUserId(body.user_id) : null
  if (!eventName || !userId || !/^[0-9]{16,22}$/.test(userId)) {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }
  const botUrl = process.env.BOT_ADMIN_URL
  if (!botUrl) return NextResponse.json({ error: 'bot_unavailable' }, { status: 503 })
  try {
    const response = await fetch(`${botUrl}/registrations/remove`, {
      method: 'POST', headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_name: eventName, user_id: userId }),
      signal: AbortSignal.timeout(30_000),
    })
    return NextResponse.json(await response.json(), { status: response.status })
  } catch {
    // Do not retry a removal automatically: the bot might already have persisted it.
    return NextResponse.json({ error: 'removal_unconfirmed' }, { status: 502 })
  }
}
