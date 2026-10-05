import { NextRequest, NextResponse } from 'next/server'
import { parseEventParam, parseUserId } from '../validation'
import { paymentRegistration } from '../payment-access'
import { getPayment, setPaid } from '../payments'

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
    const wasPaid = getPayment(eventName, userId).paid
    const payment = setPaid(eventName, userId, body.paid)
    let warning: string | undefined
    // Only notify on a real unpaid-to-paid transition, after persisting it.
    if (body.paid && !wasPaid) {
      try {
        const botUrl = process.env.BOT_ADMIN_URL
        if (!botUrl) throw new Error('bot_unavailable')
        const response = await fetch(`${botUrl}/payments/confirm`, {
          method: 'POST', headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ event_name: eventName, user_id: userId }),
          signal: AbortSignal.timeout(10_000),
        })
        if (!response.ok) throw new Error('dm_failed')
      } catch {
        warning = 'Payment was marked paid, but the confirmation DM could not be delivered.'
      }
    }
    return NextResponse.json({ payment, ...(warning ? { warning } : {}) })
  } catch {
    return NextResponse.json({ error: 'database_write_error' }, { status: 500 })
  }
}
