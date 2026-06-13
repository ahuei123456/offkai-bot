// Shared mock data + in-memory check-in store used when MOCK_MODE=true.
// Lets the full scan -> check-in -> already-checked-in flow (and cross-event
// rejection) be exercised on a test host without the bot's real JSON files.
import type { CheckinRecord } from './db'

export interface MockEvent {
  event_name: string
  venue: string
  address: string
  google_maps_link: string
  event_datetime: string
  event_deadline: string
  open: boolean
  archived: boolean
  drinks: string[]
  max_capacity: number | null
}

export interface MockAttendee {
  // String to match the real BotAttendee.user_id (Discord snowflakes are 64-bit).
  user_id: string
  username: string
  display_name: string | null
  drinks: string[]
  extra_people: number
  extras_names: string[]
  status: 'attending' | 'waitlist'
}

// Three events relative to "today" so the default-selection logic is testable:
//  - Roselia Live Offkai  -> past
//  - Bandori 10th Offkai  -> next upcoming (should be the default)
//  - MyGO!!!!! Offkai     -> further future
export const MOCK_EVENTS: MockEvent[] = [
  {
    event_name: 'Roselia Live Offkai',
    venue: 'Shinjuku Izakaya',
    address: 'Shinjuku, Tokyo',
    google_maps_link: '',
    event_datetime: '2026-05-20T13:00:00+09:00',
    event_deadline: '2026-05-18T00:00:00+09:00',
    open: false,
    archived: false,
    drinks: ['Sapporo Beer (L)', 'Oolong Tea (L)'],
    max_capacity: 20,
  },
  {
    event_name: 'Bandori 10th Offkai',
    venue: 'Akihabara Hall',
    address: 'Akihabara, Tokyo',
    google_maps_link: '',
    event_datetime: '2026-06-14T12:00:00+09:00',
    event_deadline: '2026-06-12T00:00:00+09:00',
    open: true,
    archived: false,
    drinks: ['Oolong Tea (L)', 'Cream Soda (L)', 'Coca-Cola (L)', 'Sapporo Beer (L)', 'Highball (L)', 'Fresh Lemon Sour (L)'],
    max_capacity: 30,
  },
  {
    event_name: 'MyGO!!!!! Offkai',
    venue: 'Ikebukuro Cafe',
    address: 'Ikebukuro, Tokyo',
    google_maps_link: '',
    event_datetime: '2026-07-20T13:00:00+09:00',
    event_deadline: '2026-07-18T00:00:00+09:00',
    open: true,
    archived: false,
    drinks: ['Cream Soda (L)', 'Fresh Lemon Sour (L)'],
    max_capacity: 25,
  },
]

// Distinct attendees per event so cross-event scans can be rejected.
export const MOCK_ATTENDEES: Record<string, MockAttendee[]> = {
  'Bandori 10th Offkai': [
    { user_id: '123', username: 'fadekyun', display_name: 'Fadekyun', drinks: ['Highball (L)'], extra_people: 1, extras_names: ['Senpai'], status: 'attending' },
    { user_id: '124', username: 'sakichan', display_name: 'Sakichan', drinks: ['Oolong Tea (L)', 'Cream Soda (L)'], extra_people: 0, extras_names: [], status: 'attending' },
    { user_id: '125', username: 'hoshino', display_name: 'Hoshino', drinks: ['Sapporo Beer (L)'], extra_people: 2, extras_names: ['Friend A', 'Friend B'], status: 'attending' },
    { user_id: '126', username: 'arisa', display_name: 'Arisa', drinks: ['Fresh Lemon Sour (L)'], extra_people: 0, extras_names: [], status: 'waitlist' },
  ],
  'Roselia Live Offkai': [
    { user_id: '200', username: 'yukina', display_name: 'Yukina', drinks: ['Oolong Tea (L)'], extra_people: 0, extras_names: [], status: 'attending' },
    { user_id: '201', username: 'lisa', display_name: 'Lisa', drinks: ['Sapporo Beer (L)'], extra_people: 1, extras_names: ['Ako'], status: 'attending' },
  ],
  'MyGO!!!!! Offkai': [
    { user_id: '300', username: 'tomori', display_name: 'Tomori', drinks: ['Cream Soda (L)'], extra_people: 0, extras_names: [], status: 'attending' },
    { user_id: '301', username: 'anon', display_name: 'Anon', drinks: ['Fresh Lemon Sour (L)'], extra_people: 0, extras_names: [], status: 'attending' },
  ],
}

// Process-wide in-memory check-ins for mock mode (resets on server restart).
export const mockCheckins: CheckinRecord[] = []

export function findMockAttendee(eventName: string, userId: string): MockAttendee | undefined {
  return (MOCK_ATTENDEES[eventName] || []).find(a => a.user_id === userId)
}
