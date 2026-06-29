'use client'
import { useCallback, useEffect, useState } from 'react'
import type { Attendee, AdminFilter, CheckinRecord } from '../lib/types'

const groupSize = (a: Attendee) => 1 + (a.extra_people ?? 0)

// Owns admin auth + the selected event's attendees/check-ins, the manual
// check-in/out actions, and the filtered/derived view data. The scanner hook is
// kept separate and feeds successful scans back via `applyScanCheckin`.
export function useAdminData() {
  const [key, setKey] = useState('')
  const [authed, setAuthed] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [loginError, setLoginError] = useState('')
  const [eventName, setEventName] = useState('')
  const [events, setEvents] = useState<{ event_name: string; event_datetime: string | null; open: boolean }[]>([])
  const [selectedEvent, setSelectedEvent] = useState('')
  const [attendees, setAttendees] = useState<Attendee[]>([])
  const [checkins, setCheckins] = useState<Record<string, CheckinRecord>>({})
  const [filter, setFilter] = useState<AdminFilter>('all')
  const [search, setSearch] = useState('')
  // Rows the admin just checked in/out — kept visible regardless of the active
  // filter so a mistaken action can be undone in place (e.g. on the Pending tab).
  const [stickyIds, setStickyIds] = useState<Set<string>>(new Set())

  const loadCheckins = useCallback(async (adminKey: string, ev: string) => {
    const evParam = ev ? `&event=${encodeURIComponent(ev)}` : ''
    const res = await fetch(`/api/checkin?key=${encodeURIComponent(adminKey)}${evParam}`)
    if (!res.ok) return
    const chk: CheckinRecord[] = await res.json()
    setCheckins(Object.fromEntries(chk.map(c => [c.user_id, c])))
  }, [])

  const loadAttendees = useCallback(async (adminKey: string, ev: string) => {
    const evParam = ev ? `&event=${encodeURIComponent(ev)}` : ''
    const res = await fetch(`/api/attendees?key=${encodeURIComponent(adminKey)}${evParam}`)
    if (!res.ok) return false
    const { event_name, attendees: att } = await res.json()
    setEventName(event_name)
    setAttendees(att)
    return true
  }, [])

  // Initial load after login: fetch event list + default, then its data.
  const initialLoad = useCallback(async (adminKey: string) => {
    const evRes = await fetch(`/api/events?key=${encodeURIComponent(adminKey)}`)
    if (!evRes.ok) return false
    const { events: evs, default_event_name } = await evRes.json()
    const startEvent: string = default_event_name || (evs[0]?.event_name ?? '')
    setEvents(evs)
    setSelectedEvent(startEvent)
    const ok = await loadAttendees(adminKey, startEvent)
    if (!ok) return false
    await loadCheckins(adminKey, startEvent)
    return true
  }, [loadAttendees, loadCheckins])

  const handleLogin = useCallback(async () => {
    const ok = await initialLoad(keyInput)
    if (ok) { setKey(keyInput); setAuthed(true); setLoginError('') }
    else setLoginError('Invalid key. Check with the event host.')
  }, [keyInput, initialLoad])

  // Refresh attendee list + check-ins whenever the selected event changes.
  useEffect(() => {
    if (!authed || !selectedEvent) return
    let cancelled = false
    const run = async () => {
      await loadAttendees(key, selectedEvent)
      if (!cancelled) await loadCheckins(key, selectedEvent)
    }
    run()
    return () => { cancelled = true }
  }, [authed, selectedEvent, key, loadAttendees, loadCheckins])

  // Poll check-ins for the selected event every 10s.
  useEffect(() => {
    if (!authed || !selectedEvent) return
    const id = setInterval(() => loadCheckins(key, selectedEvent), 10_000)
    return () => clearInterval(id)
  }, [authed, selectedEvent, key, loadCheckins])

  // Switch the viewed event (resets transient view state at the source, not in
  // an effect, per react-hooks guidance).
  const changeEvent = useCallback((next: string) => {
    setSelectedEvent(next)
    setStickyIds(new Set())
  }, [])

  const changeFilter = useCallback((next: AdminFilter) => {
    setFilter(next)
    setStickyIds(new Set())
  }, [])

  // Manual check-in (admin button) — no QR needed, admin is already authed.
  const manualCheckin = useCallback(async (userId: string) => {
    const evParam = selectedEvent ? `&event=${encodeURIComponent(selectedEvent)}` : ''
    const res = await fetch(`/api/checkin?key=${encodeURIComponent(key)}${evParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, event_name: selectedEvent || undefined }),
    })
    const data = await res.json().catch(() => ({}))
    if (res.ok && data.record) {
      setCheckins(prev => ({ ...prev, [data.record.user_id]: data.record }))
      setStickyIds(prev => new Set(prev).add(userId))
    }
  }, [key, selectedEvent])

  // Manual check-out (admin button) — removes the check-in for this event.
  // Uses POST with action=checkout because some proxies reject the DELETE method.
  const manualCheckout = useCallback(async (userId: string) => {
    const evParam = selectedEvent ? `&event=${encodeURIComponent(selectedEvent)}` : ''
    const res = await fetch(`/api/checkin?key=${encodeURIComponent(key)}${evParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'checkout', user_id: userId, event_name: selectedEvent || undefined }),
    })
    if (res.ok) {
      setCheckins(prev => {
        const next = { ...prev }
        delete next[userId]
        return next
      })
      setStickyIds(prev => new Set(prev).add(userId))
    }
  }, [key, selectedEvent])

  // Record a successful camera scan into the check-in map (no sticky — scans
  // aren't undo-in-place like the manual buttons).
  const applyScanCheckin = useCallback((record: CheckinRecord) => {
    setCheckins(prev => ({ ...prev, [record.user_id]: record }))
  }, [])

  // Header counters reflect physical people, not RSVP records: each attending
  // record is the primary attendee plus their extra_people guests, who check in
  // as one group via the primary's single QR / manual action (issue #80).
  const attending = attendees.filter(a => a.status === 'attending')
  const attendingCount = attending.reduce((total, a) => total + groupSize(a), 0)
  const checkedInCount = attending
    .filter(a => checkins[a.user_id])
    .reduce((total, a) => total + groupSize(a), 0)
  const pendingCount = attendingCount - checkedInCount
  const waitlist = attendees.filter(a => a.status === 'waitlist')

  const filtered = attending
    .filter(a => {
      if (stickyIds.has(a.user_id)) return true
      if (filter === 'checked') return !!checkins[a.user_id]
      if (filter === 'pending') return !checkins[a.user_id]
      return true
    })
    .filter(a => {
      if (!search) return true
      const q = search.toLowerCase().replace(/^[@#]/, '')
      const numbers = [a.attendee_number, ...(a.extras_attendee_numbers ?? [])].filter(n => n != null).map(String)
      return [a.display_name || '', a.username, a.user_id, ...a.drinks, ...a.extras_names, ...numbers]
        .some(v => v.toLowerCase().includes(q))
    })

  return {
    key, authed, keyInput, setKeyInput, loginError, handleLogin,
    eventName, events, selectedEvent, changeEvent,
    attendees, checkins, applyScanCheckin, manualCheckin, manualCheckout,
    filter, changeFilter, search, setSearch,
    filtered, waitlist, pendingCount, checkedInCount, attendingCount,
    waitlistCount: waitlist.length,
  }
}
