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

export function getActiveEvent(events: Event[]): Event | null {
  if (events.length === 0) return null
  const active = events.find(e => !e.archived)
  if (active) return active
  return events[events.length - 1]
}
