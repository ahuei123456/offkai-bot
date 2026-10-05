import { NextRequest, NextResponse } from 'next/server'
import { verifyToken } from '../token'
import { parseEventParam, parseUserId } from '../validation'
import { paymentRegistration, tokenPaymentRegistration } from '../payment-access'
import { getPayment, MAX_IMAGE_BYTES, proofExpiry, readProof, saveProof } from '../payments'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
const PRIVATE_HEADERS = { 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff' }
function error(message: string, status: number) {
  return NextResponse.json({ error: message }, { status, headers: PRIVATE_HEADERS })
}
export async function POST(request: NextRequest) {
  // Bound multipart overhead too, before allocating the uploaded image.
  const length = Number(request.headers.get('content-length'))
  if (length > MAX_IMAGE_BYTES + 64 * 1024) return error('image_too_large', 413)
  try {
    if (!request.body) return error('missing_image', 400)
    const reader = request.body.getReader()
    const chunks: Uint8Array[] = []
    let bytes = 0
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      bytes += value.byteLength
      if (bytes > MAX_IMAGE_BYTES + 64 * 1024) {
        await reader.cancel()
        return error('image_too_large', 413)
      }
      chunks.push(value)
    }
    const multipart = Buffer.concat(chunks)
    const form = await new Response(new Uint8Array(multipart), {
      headers: { 'Content-Type': request.headers.get('content-type') || '' },
    }).formData()
    const raw = form.get('token')
    const token = verifyToken(typeof raw === 'string' ? raw : '')
    if (!token) return error('unauthorized', 401)
    const registration = tokenPaymentRegistration(token)
    if (!registration) return error('not_found', 404)
    const eventStart = registration.event.event_datetime
    if (!eventStart || Date.parse(proofExpiry(eventStart)) <= Date.now()) return error('proof_expired', 410)
    const image = form.get('image')
    if (!(image instanceof File)) return error('missing_image', 400)
    if (image.size > MAX_IMAGE_BYTES) return error('image_too_large', 413)
    if (!['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(image.type)) return error('invalid_image', 400)
    const replaced = !!getPayment(registration.event.event_name, token.userId).proof
    const payment = await saveProof(registration.event.event_name, token.userId, eventStart,
      Buffer.from(await image.arrayBuffer()))
    return NextResponse.json({ payment, replaced }, { headers: PRIVATE_HEADERS })
  } catch {
    return error('invalid_image_or_storage_error', 400)
  }
}
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  const key = process.env.ADMIN_KEY
  let registration
  let userId: string
  if (params.has('token')) {
    const token = verifyToken(params.get('token') || '')
    if (!token) return error('unauthorized', 401)
    registration = tokenPaymentRegistration(token)
    userId = token.userId
  } else {
    if (!key || params.get('key') !== key) return error('unauthorized', 401)
    const eventName = parseEventParam(params.get('event'))
    const parsedId = parseUserId(params.get('user_id'))
    if (!eventName || !parsedId) return error('invalid_request', 400)
    registration = paymentRegistration(eventName, parsedId)
    userId = parsedId
  }
  if (!registration) return error('not_found', 404)
  try {
    const start = registration.event.event_datetime
    if (!start || Date.parse(proofExpiry(start)) <= Date.now()) return error('proof_expired', 410)
    const proof = readProof(registration.event.event_name, userId, start)
    if (!proof) return error('not_found', 404)
    return new NextResponse(new Uint8Array(proof), { headers: { ...PRIVATE_HEADERS, 'Content-Type': 'image/webp' } })
  } catch {
    return error('storage_error', 500)
  }
}
