// Shared input validation for the admin/check-in API routes, so attendees,
// checkin, checkout and events all validate identically (no drift).

export const MAX_EVENT_NAME_LEN = 200

// Validates an optional event name (query param or body field).
// Returns the trimmed string, `null` when absent, or `false` when malformed.
export function parseEventParam(raw: unknown): string | null | false {
  if (raw === null || raw === undefined) return null
  if (typeof raw !== 'string' || raw.length > MAX_EVENT_NAME_LEN) return false
  const trimmed = raw.trim()
  if (!trimmed) return false
  return trimmed
}

// Validates a manual user_id (number or numeric string).
// Returns the canonical string form, or null if invalid.
export function parseUserId(raw: unknown): string | null {
  if (typeof raw !== 'number' && typeof raw !== 'string') return null
  const n = Number(raw)
  if (!Number.isFinite(n) || !Number.isInteger(n) || n < 0) return null
  return String(n)
}
