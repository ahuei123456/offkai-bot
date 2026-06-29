// Shared client-side view types for the attendee pass + admin check-in UI.

export type ViewState = 'loading' | 'no_token' | 'invalid' | 'not_found' | 'unavailable' | 'ready'

export type AttendeeData = { attendee: Record<string, unknown>; event: Record<string, unknown> }

export type Attendee = {
  // Discord snowflake ID as a string (64-bit, exceeds JS safe-integer range).
  user_id: string
  username: string
  display_name: string | null
  drinks: string[]
  extra_people: number
  extras_names: string[]
  attendee_number: number | null
  extras_attendee_numbers: number[]
  status: 'attending' | 'waitlist'
}

export type CheckinRecord = {
  user_id: string
  event_name: string
  checked_in_at: string
  name: string
}

export type EventOption = {
  event_name: string
  event_datetime: string | null
  open: boolean
}

export type AdminFilter = 'all' | 'checked' | 'pending'

// Scanner result is keyed by a stable `kind` (not display wording) so the badge
// and styling stay correct even if the copy changes.
export type ScanResultKind = 'checked_in' | 'already_checked_in' | 'wrong_event' | 'invalid_qr' | 'error'

export type ScanResult = {
  kind: ScanResultKind
  name: string
  // True when produced by a live camera decode, so the popup auto-dismisses and
  // the scanner resumes (manual/setup errors stay until dismissed).
  fromScan: boolean
  extraPeople?: number
  extrasNames?: string[]
  attendeeNumber?: number | null
  extrasNumbers?: number[]
  time?: string
}
