import { NextRequest, NextResponse } from 'next/server'
import { parseEventParam, parseUserId } from '../validation'
import { paymentRegistration } from '../payment-access'
import { setPaid } from '../payments'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(request: NextRequest) {
  const key = process.env.ADMIN_KEY
  if (!key || request.nextUrl.searchParams.get('key') !== key) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }
  const body = await request.json().catch(() => null)
  const eventName = parseEventParam(body?.event_name)
  const userId = parseUserId(body?.user_id)
  if (!eventName || !userId || typeof body?.paid !== 'boolean') {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }
  if (!paymentRegistration(eventName, userId)) return NextResponse.json({ error: 'not_found' }, { status: 404 })
  try {
    return NextResponse.json({ payment: setPaid(eventName, userId, body.paid) })
  } catch {
    return NextResponse.json({ error: 'database_write_error' }, { status: 500 })
  }
}
