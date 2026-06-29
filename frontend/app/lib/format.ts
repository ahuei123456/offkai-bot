import type { Strings } from './i18n'
import type { EventOption } from './types'

// Cached JST formatter so the live-clock rAF loop allocates nothing per frame.
export const JST_HMS = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Tokyo', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
})

// Full drink-card palette (background, border, accent strip) for the pass.
export function getDrinkColors(name: string) {
  const n = name.toLowerCase()
  if (n.includes('oolong'))      return { bg: 'bg-[#F3E8DE]', border: 'border-[#D4BC9E]', strip: 'bg-[#8B5E34]' }
  if (n.includes('cream soda')) return { bg: 'bg-green-50',   border: 'border-green-200',  strip: 'bg-green-500' }
  if (n.includes('coca') || n.includes('coke')) return { bg: 'bg-red-50', border: 'border-red-200', strip: 'bg-red-500' }
  if (n.includes('sapporo') || n.includes('beer')) return { bg: 'bg-amber-50', border: 'border-amber-200', strip: 'bg-amber-400' }
  if (n.includes('highball'))    return { bg: 'bg-orange-50',  border: 'border-orange-200', strip: 'bg-orange-600' }
  if (n.includes('lemon'))       return { bg: 'bg-yellow-50',  border: 'border-yellow-200', strip: 'bg-yellow-400' }
  return { bg: 'bg-white', border: 'border-[#17120F]', strip: 'bg-[#17120F]' }
}

// Compact dot colour for the admin attendee rows.
export function drinkDot(name: string) {
  const n = name.toLowerCase()
  if (n.includes('oolong'))      return 'bg-[#8B5E34]'
  if (n.includes('cream soda')) return 'bg-green-500'
  if (n.includes('coca') || n.includes('coke')) return 'bg-red-500'
  if (n.includes('sapporo') || n.includes('beer')) return 'bg-amber-400'
  if (n.includes('highball'))    return 'bg-orange-500'
  if (n.includes('lemon'))       return 'bg-yellow-400'
  return 'bg-gray-400'
}

export function formatArrivalTime(iso: string, t: Strings) {
  if (!iso) return t.tbd
  try {
    return new Date(iso).toLocaleTimeString('en-GB', {
      timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit',
    }) + ' JST'
  } catch { return t.tbd }
}

export function getEventPhase(iso: string, t: Strings) {
  if (!iso) return t.datePending
  const eventTime = new Date(iso).getTime()
  if (Number.isNaN(eventTime)) return t.datePending
  const diffMinutes = Math.round((eventTime - Date.now()) / 60000)
  if (diffMinutes > 90) return t.startsOn(new Date(iso).toLocaleDateString(t.locale, { timeZone: 'Asia/Tokyo', month: 'short', day: 'numeric' }))
  if (diffMinutes > 0) return t.startsIn(diffMinutes)
  if (diffMinutes > -180) return t.happeningNow
  return t.eventEnded
}

export function formatEventLabel(ev: EventOption) {
  let when = ''
  if (ev.event_datetime) {
    try {
      when = ' — ' + new Date(ev.event_datetime).toLocaleDateString('en-GB', {
        timeZone: 'Asia/Tokyo', day: '2-digit', month: 'short',
      })
    } catch { /* ignore */ }
  }
  return `${ev.event_name}${when}${ev.open ? '' : ' (closed)'}`
}
