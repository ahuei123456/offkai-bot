type CheckinIdentity = { user_id: string; event_name: string; registration_timestamp?: string }

// Legacy records are deliberately unbound: neither their scan time nor the
// signup promise proves that a replacement registration physically arrived.
export function matchesCheckin(record: CheckinIdentity | undefined, eventName: string, userId: string,
  timestamp: string | null | undefined): boolean {
  if (!record || record.event_name !== eventName || record.user_id !== userId ||
      !record.registration_timestamp || !timestamp) return false
  const identity = Date.parse(timestamp)
  return Number.isFinite(identity) && Date.parse(record.registration_timestamp) === identity
}
