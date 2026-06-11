import fs from 'fs'
import path from 'path'

export interface Event {
  event_name: string
  venue: string | null
  address: string | null
  google_maps_link: string | null
  event_datetime: string | null
  event_deadline: string | null
  open: boolean
  archived: boolean
  drinks: string[]
  max_capacity: number | null
}

export interface BotAttendee {
  user_id: number
  username: string
  display_name: string | null
  drinks: string[]
  extra_people: number
  extras_names: string[]
  behavior_confirmed: boolean
  arrival_confirmed: boolean
  event_name: string
  timestamp: string
}

export interface BotEventResponses {
  attendees: BotAttendee[]
  waitlist: BotAttendee[]
}

export interface BotResponses {
  [eventName: string]: BotEventResponses
}

export interface CheckinRecord {
  user_id: number
  event_name: string
  checked_in_at: string
  name: string
}

const BOT_DATA_DIR = process.env.BOT_DATA_DIR ||
  (fs.existsSync('/app/offkai-bot-data') ? '/app/offkai-bot-data' : path.join(process.cwd(), '..', 'data'))

export function getEventsFilePath() {
  return path.join(BOT_DATA_DIR, 'events.json')
}

export function getResponsesFilePath() {
  return path.join(BOT_DATA_DIR, 'responses.json')
}

export function getCheckinsFilePath() {
  return path.join(BOT_DATA_DIR, 'checkins.json')
}

export function readEvents(): Event[] {
  const filePath = getEventsFilePath()
  if (!fs.existsSync(filePath)) return []
  try {
    const data = fs.readFileSync(filePath, 'utf8')
    return JSON.parse(data)
  } catch (e) {
    console.error('Error reading events:', e)
    return []
  }
}

export function readResponses(): BotResponses {
  const filePath = getResponsesFilePath()
  if (!fs.existsSync(filePath)) return {}
  try {
    const data = fs.readFileSync(filePath, 'utf8')
    return JSON.parse(data)
  } catch (e) {
    console.error('Error reading responses:', e)
    return {}
  }
}

export function readCheckins(): CheckinRecord[] {
  const filePath = getCheckinsFilePath()
  if (!fs.existsSync(filePath)) return []
  try {
    const data = fs.readFileSync(filePath, 'utf8')
    return JSON.parse(data)
  } catch (e) {
    console.error('Error reading checkins:', e)
    return []
  }
}

export function writeCheckins(checkins: CheckinRecord[]): boolean {
  const filePath = getCheckinsFilePath()
  try {
    const dir = path.dirname(filePath)
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true })
    }
    fs.writeFileSync(filePath, JSON.stringify(checkins, null, 2), 'utf8')
    return true
  } catch (e) {
    console.error('Error writing checkins:', e)
    return false
  }
}

// Returns the JST calendar day of a date as a YYYYMMDD integer, so two dates
// can be compared by day without timezone drift (events are authored in JST).
function jstDayNumber(d: Date): number {
  const s = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(d)
  return parseInt(s.replace(/-/g, ''), 10)
}

// Minimal shape the default-selection logic needs — satisfied by both the real
// Event and the MOCK_EVENTS entries.
export interface EventLike {
  event_name: string
  event_datetime: string | null
  archived: boolean
}

// Default event for the admin dropdown (issue #77):
//  - the next upcoming non-archived event (earliest event whose JST date is today
//    or later — so an event still counts as the default on the day it happens)
//  - if every event is in the past, the most recent past one
export function getDefaultEvent<T extends EventLike>(events: T[]): T | null {
  const dated = events.filter(e => !e.archived && e.event_datetime)
  if (dated.length === 0) {
    const nonArchived = events.filter(e => !e.archived)
    if (nonArchived.length > 0) return nonArchived[nonArchived.length - 1]
    return events.length > 0 ? events[events.length - 1] : null
  }

  const todayKey = jstDayNumber(new Date())
  const byTime = (a: T, b: T) =>
    new Date(a.event_datetime!).getTime() - new Date(b.event_datetime!).getTime()

  const upcoming = dated
    .filter(e => jstDayNumber(new Date(e.event_datetime!)) >= todayKey)
    .sort(byTime)
  if (upcoming.length > 0) return upcoming[0]

  // All past — pick the most recent.
  return [...dated].sort(byTime).reverse()[0]
}

export function getActiveEvent(events: Event[]): Event | null {
  if (events.length === 0) return null

  // 1. Try to find the latest open and non-archived event (searching from most recent to oldest)
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.open && !e.archived) {
      return e
    }
  }

  // 2. Fallback to the latest non-archived event (searching from most recent to oldest)
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (!e.archived) {
      return e
    }
  }

  // 3. Fallback to the last event in the list
  return events[events.length - 1]
}
