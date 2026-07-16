import crypto from 'crypto'

// Check-in token verification.
//
// Two formats are accepted:
//
//   legacy : <user_id>.<sig>
//            sig = HMAC-SHA256(ADMIN_KEY, "<user_id>")[:16]
//            (the event is NOT encoded, so it stays ambiguous)
//
//   v2     : v2.<payload>.<sig>
//            payload = base64url("<user_id>:<event_name>")
//            sig     = HMAC-SHA256(ADMIN_KEY, payload)[:16]
//            (the event IS encoded and signed, so an old QR can never silently
//             resolve to a newer event — issue #77 / PR #78 review)
//
// The bot mints these tokens (bot/src/offkai_bot/util.py + interactions.py).
// The frontend only verifies. To roll out v2 end-to-end the bot must emit the
// v2 format; until then legacy tokens keep working unchanged.

const ADMIN_KEY = process.env.ADMIN_KEY ?? ''
const MAX_TOKEN_LEN = 2048

export interface ResolvedToken {
  userId: string
  // The event the token is bound to, or null for legacy (event-less) tokens.
  eventName: string | null
}

function hmac16(message: string): string {
  return crypto.createHmac('sha256', ADMIN_KEY).update(message).digest('hex').substring(0, 16)
}

// Constant-time string comparison (issue: timing-safe HMAC comparison).
function timingSafeStrEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a, 'utf8')
  const bb = Buffer.from(b, 'utf8')
  if (ab.length !== bb.length) return false
  return crypto.timingSafeEqual(ab, bb)
}

// Verifies a raw token string. Returns the resolved {userId, eventName} or null
// if the token is malformed or the signature does not verify.
export function verifyToken(raw: string): ResolvedToken | null {
  if (typeof raw !== 'string' || !raw || raw.length > MAX_TOKEN_LEN) return null
  const token = raw.trim()

  // Without a configured key we cannot verify signatures, so no token is
  // acceptable (fail closed — a bare user_id would be forgeable, since
  // Discord user IDs are public; issue #101).
  if (!ADMIN_KEY) return null

  const parts = token.split('.')

  // v2.<payload>.<sig>
  if (parts.length === 3 && parts[0] === 'v2') {
    const payload = parts[1]
    const sig = parts[2].toLowerCase()
    if (!payload || !sig) return null
    if (!timingSafeStrEqual(sig, hmac16(payload))) return null

    let decoded: string
    try {
      decoded = Buffer.from(payload, 'base64url').toString('utf8')
    } catch {
      return null
    }
    const sep = decoded.indexOf(':')
    if (sep < 0) return null
    const userId = decoded.slice(0, sep)
    const eventName = decoded.slice(sep + 1).trim()
    if (!/^\d+$/.test(userId) || !eventName) return null
    return { userId, eventName }
  }

  // legacy <user_id>.<sig>
  if (parts.length === 2) {
    const userId = parts[0]
    const sig = parts[1].toLowerCase()
    if (!/^\d+$/.test(userId) || !sig) return null
    if (!timingSafeStrEqual(sig, hmac16(userId))) return null
    return { userId, eventName: null }
  }

  return null
}
