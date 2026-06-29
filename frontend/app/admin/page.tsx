'use client'
import { useState, useEffect, useRef, useCallback } from 'react'
import { flushSync } from 'react-dom'

type Attendee = {
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

type CheckinRecord = {
  user_id: string
  event_name: string
  checked_in_at: string
  name: string
}

type EventOption = {
  event_name: string
  event_datetime: string | null
  open: boolean
}

// Scanner result is keyed by a stable `kind` (not display wording) so the badge
// and styling stay correct even if the copy changes.
type ScanResultKind = 'checked_in' | 'already_checked_in' | 'wrong_event' | 'invalid_qr' | 'error'
type ScanResult = {
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

// How long the scan popup stays up before auto-dismissing and resuming scanning.
const POPUP_MS: Record<ScanResultKind, number> = {
  checked_in: 3500, already_checked_in: 3500, wrong_event: 4500, invalid_qr: 4500, error: 6000,
}

const SCAN_RESULT_META: Record<ScanResultKind, { ok: boolean; badge: string; title: string }> = {
  checked_in:         { ok: true,  badge: 'OK',    title: 'Checked In!' },
  already_checked_in: { ok: true,  badge: 'Again', title: 'Already Checked In' },
  wrong_event:        { ok: false, badge: 'Stop',  title: 'Wrong Event' },
  invalid_qr:         { ok: false, badge: 'NG',    title: 'Invalid QR' },
  error:              { ok: false, badge: 'NG',    title: 'Camera Error' },
}

function drinkDot(name: string) {
  const n = name.toLowerCase()
  if (n.includes('oolong'))      return 'bg-[#8B5E34]'
  if (n.includes('cream soda')) return 'bg-green-500'
  if (n.includes('coca') || n.includes('coke')) return 'bg-red-500'
  if (n.includes('sapporo') || n.includes('beer')) return 'bg-amber-400'
  if (n.includes('highball'))    return 'bg-orange-500'
  if (n.includes('lemon'))       return 'bg-yellow-400'
  return 'bg-gray-400'
}

function formatEventLabel(ev: EventOption) {
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

function SmileyMark({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <circle cx="20" cy="20" r="18" fill="#E51F1F" stroke="#17120F" strokeWidth="2.5" />
      <circle cx="13" cy="16.5" r="2.6" fill="#17120F" />
      <circle cx="27" cy="16.5" r="2.6" fill="#17120F" />
      <path d="M11 22 q9 11 18 0" fill="none" stroke="#17120F" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

// Cached JST formatter so the rAF loop allocates nothing per frame.
const JST_HMS = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Tokyo', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
})

// Live JST clock with milliseconds, shown in the scan popup so the confirmation
// reads as a live event. Writes textContent via a ref — no React state, so it
// never re-renders the tree (a 60fps setState would thrash the app).
function LiveClock() {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const d = new Date()
      const el = ref.current
      if (el) el.textContent = `${JST_HMS.format(d)}.${String(d.getMilliseconds()).padStart(3, '0')} JST`
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
  return (
    <div className="mx-auto mt-3 inline-flex items-center gap-2 rounded-xl border-2 border-[#17120F] bg-[#17120F] px-3 py-1.5">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-[#3CCB5A]" aria-hidden="true" />
      <span className="text-[9px] font-black uppercase tracking-[0.2em] text-[#FFD51B]">Live</span>
      <span ref={ref} className="font-mono text-sm font-black tabular-nums text-white">--:--:--.--- JST</span>
    </div>
  )
}

function BrandSign({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <div className="inline-flex items-center gap-1.5">
        <SmileyMark className="h-7 w-7 shrink-0 -rotate-6" />
        <span className="brand-wordmark text-2xl leading-none">Offkai Bot</span>
      </div>
    )
  }
  return (
    <div className="inline-flex flex-col items-start">
      <span className="brand-banner inline-block rounded-lg px-2.5 py-0.5 text-[10px] tracking-[0.3em]">大衆酒場</span>
      <div className="mt-1.5 flex items-end gap-1">
        <span className="brand-wordmark text-4xl leading-[0.9]">Offkai Bot</span>
        <SmileyMark className="mb-1 h-7 w-7 shrink-0 -rotate-6 drop-shadow-[2px_2px_0_#17120F]" />
      </div>
    </div>
  )
}

export default function AdminPage() {
  const [key, setKey] = useState('')
  const [authed, setAuthed] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [loginError, setLoginError] = useState('')
  const [eventName, setEventName] = useState('')
  const [events, setEvents] = useState<EventOption[]>([])
  const [selectedEvent, setSelectedEvent] = useState('')
  const [attendees, setAttendees] = useState<Attendee[]>([])
  const [checkins, setCheckins] = useState<Record<string, CheckinRecord>>({})
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [popupMsLeft, setPopupMsLeft] = useState(0)
  const [filter, setFilter] = useState<'all' | 'checked' | 'pending'>('all')
  const [search, setSearch] = useState('')
  // Rows the admin just checked in/out — kept visible regardless of the active
  // filter so a mistaken action can be undone in place (e.g. on the Pending tab).
  const [stickyIds, setStickyIds] = useState<Set<string>>(new Set())

  const scannerRef = useRef<{ stop: () => Promise<void>; clear?: () => void } | null>(null)
  const Html5QrcodeRef = useRef<typeof import('html5-qrcode').Html5Qrcode | null>(null)
  const selectedEventRef = useRef('')
  const keyRef = useRef('')
  const attendeesRef = useRef<Attendee[]>([])
  const scannerDivId = 'qr-scanner-container'

  // Keep refs in sync so the scan callback always reads current values.
  useEffect(() => { selectedEventRef.current = selectedEvent }, [selectedEvent])
  useEffect(() => { keyRef.current = key }, [key])
  useEffect(() => { attendeesRef.current = attendees }, [attendees])

  // Pre-load the QR library on mount. Importing it inside the click handler is a
  // network fetch that crosses a task boundary and revokes the browser's
  // user-gesture context, which makes getUserMedia throw NotAllowedError on
  // iOS/Android even after the user grants the camera permission.
  useEffect(() => {
    let cancelled = false
    import('html5-qrcode').then(({ Html5Qrcode }) => {
      if (!cancelled) Html5QrcodeRef.current = Html5Qrcode
    }).catch(() => { /* surfaced on first scan attempt */ })
    return () => { cancelled = true }
  }, [])

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

  const handleLogin = async () => {
    const ok = await initialLoad(keyInput)
    if (ok) { setKey(keyInput); setAuthed(true); setLoginError('') }
    else setLoginError('Invalid key. Check with the event host.')
  }

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

  // Switch the viewed event (resets transient view state at the source, not in
  // an effect, per react-hooks guidance).
  const changeEvent = useCallback((next: string) => {
    setSelectedEvent(next)
    setScanResult(null)
    setStickyIds(new Set())
  }, [])

  const changeFilter = useCallback((next: 'all' | 'checked' | 'pending') => {
    setFilter(next)
    setStickyIds(new Set())
  }, [])

  // Poll check-ins for the selected event every 10s.
  useEffect(() => {
    if (!authed || !selectedEvent) return
    const id = setInterval(() => loadCheckins(key, selectedEvent), 10_000)
    return () => clearInterval(id)
  }, [authed, selectedEvent, key, loadCheckins])

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

  // Show a scan result and seed its countdown here (event-handler context) so
  // the lifecycle effect only has to tick the timer down, never seed it.
  const presentScan = useCallback((r: ScanResult) => {
    setScanResult(r)
    setPopupMsLeft(r.fromScan && r.kind !== 'error' ? POPUP_MS[r.kind] : 0)
  }, [])

  const stopScanner = useCallback(async () => {
    if (scannerRef.current) {
      try { await scannerRef.current.stop() } catch { /* ignore */ }
      try { scannerRef.current.clear?.() } catch { /* ignore */ }
      scannerRef.current = null
    }
    setScanning(false)
  }, [])

  const startScanner = useCallback(async () => {
    const QrScanner = Html5QrcodeRef.current
    if (!QrScanner) {
      presentScan({ kind: 'error', name: 'Scanner not ready — reload the page and try again', fromScan: false })
      return
    }

    // flushSync so the target div is in the DOM with real dimensions before
    // html5-qrcode measures it.
    flushSync(() => {
      setScanResult(null)
      setScanning(true)
    })

    const scanner = new QrScanner(scannerDivId)
    scannerRef.current = scanner

    try {
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 250, height: 250 } },
        async (decodedText: string) => {
          await stopScanner()

          // Extract the token. Only accept QR codes whose URL is the SAME ORIGIN
          // as this admin page, so a malicious QR can't smuggle in a foreign
          // link — and we never navigate to the decoded value, only read its
          // token. Assumes attendees + admin are served from one public domain
          // (e.g. https://offkai.example.com/?token=... and /admin). It would
          // reject valid QRs if staff opened admin on a different origin such as
          // a LAN IP (http://192.168.x.x:8090/admin); loosen here if that's ever
          // needed.
          let token: string | null = null
          try {
            const url = new URL(decodedText)
            if (url.origin !== window.location.origin) {
              presentScan({ kind: 'invalid_qr', name: 'This code is not from this site', fromScan: true })
              return
            }
            token = url.searchParams.get('token')
          } catch {
            // Not a URL — treat the raw text as the token.
            token = decodedText
          }

          if (!token) {
            presentScan({ kind: 'invalid_qr', name: 'No check-in token found', fromScan: true })
            return
          }

          const ev = selectedEventRef.current
          const evParam = ev ? `&event=${encodeURIComponent(ev)}` : ''
          const res = await fetch(`/api/checkin?key=${encodeURIComponent(keyRef.current)}${evParam}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, event_name: ev || undefined }),
          })
          const data = await res.json().catch(() => ({}))

          if (res.ok && data.record) {
            const att = attendeesRef.current.find(a => a.user_id === data.record.user_id)
            presentScan({
              kind: data.already_checked_in ? 'already_checked_in' : 'checked_in',
              name: data.record.name || 'Guest',
              fromScan: true,
              extraPeople: att?.extra_people ?? 0,
              extrasNames: att?.extras_names ?? [],
              attendeeNumber: att?.attendee_number ?? null,
              extrasNumbers: att?.extras_attendee_numbers ?? [],
              time: new Date(data.record.checked_in_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
            })
            setCheckins(prev => ({ ...prev, [data.record.user_id]: data.record }))
          } else if (data.error === 'wrong_event') {
            presentScan({ kind: 'wrong_event', name: `QR is for "${data.token_event}", not the selected event`, fromScan: true })
          } else if (data.error === 'attendee_not_in_event') {
            presentScan({ kind: 'wrong_event', name: 'Not registered for this event', fromScan: true })
          } else {
            presentScan({ kind: 'invalid_qr', name: 'QR code not recognised', fromScan: true })
          }
        },
        () => { /* per-frame decode misses — ignore */ }
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const lower = msg.toLowerCase()
      const isPermission = lower.includes('notallowed') || lower.includes('permission') || lower.includes('denied')
      const noCamera = lower.includes('notfound') || lower.includes('no camera') || lower.includes('overconstrained')
      setScanning(false)
      scannerRef.current = null
      presentScan({
        kind: 'error',
        fromScan: false,
        name: isPermission
          ? 'Camera blocked. Allow camera access in your browser settings, then reload.'
          : noCamera
            ? 'No camera found on this device.'
            : msg,
      })
    }
  }, [stopScanner, presentScan])

  // Scan popup lifecycle: a live decode shows a full-screen confirmation with a
  // millisecond countdown, then auto-dismisses and resumes scanning so staff can
  // keep waving QRs through. Setup/camera errors (fromScan=false) wait for a tap.
  useEffect(() => {
    if (!scanResult || !scanResult.fromScan) return
    const total = POPUP_MS[scanResult.kind]
    const start = Date.now()
    const id = setInterval(() => {
      const left = total - (Date.now() - start)
      if (left <= 0) {
        clearInterval(id)
        setPopupMsLeft(0)
        setScanResult(null)
        if (scanResult.kind !== 'error') startScanner()
      } else {
        setPopupMsLeft(left)
      }
    }, 47)
    return () => clearInterval(id)
  }, [scanResult, startScanner])

  const dismissPopup = useCallback(() => {
    const wasScan = scanResult?.fromScan && scanResult.kind !== 'error'
    setScanResult(null)
    if (wasScan) startScanner()
  }, [scanResult, startScanner])

  // Header counters reflect physical people, not RSVP records: each attending
  // record is the primary attendee plus their extra_people guests, who check in
  // as one group via the primary's single QR / manual action (issue #80).
  const groupSize = (a: Attendee) => 1 + (a.extra_people ?? 0)
  const attendingCount = attendees
    .filter(a => a.status === 'attending')
    .reduce((total, a) => total + groupSize(a), 0)
  const checkedInCount = attendees
    .filter(a => a.status === 'attending' && checkins[a.user_id])
    .reduce((total, a) => total + groupSize(a), 0)
  const pendingCount = attendingCount - checkedInCount
  const waitlistCount = attendees.filter(a => a.status === 'waitlist').length

  const filtered = attendees
    .filter(a => a.status === 'attending')
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

  if (!authed) {
    return (
      <main className="brand-rays min-h-dvh flex items-center justify-center p-6">
        <div className="brand-card w-full max-w-sm rounded-3xl p-7">
          <BrandSign />
          <p className="mt-7 text-[10px] font-black uppercase tracking-[0.22em] text-[#8B2D1F]">Staff Access</p>
          <h1 className="mt-2 font-display text-2xl uppercase text-[#17120F] tracking-tight">Check-In Admin</h1>
          <label htmlFor="admin-key" className="block text-[10px] font-black uppercase tracking-widest text-[#8B2D1F] mt-6 mb-2">
            Admin key
          </label>
          <input
            id="admin-key"
            type="password"
            placeholder="Admin key"
            value={keyInput}
            onChange={e => setKeyInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !!keyInput.trim() && handleLogin()}
            aria-invalid={!!loginError}
            aria-describedby={loginError ? 'admin-login-error' : undefined}
            className="w-full border-2 border-[#17120F] rounded-xl px-4 py-3 text-[#17120F] font-bold bg-white mb-2 outline-none focus:border-[#E51F1F]"
          />
          {loginError && (
            <p id="admin-login-error" role="alert" className="text-sm font-bold text-red-700 mb-3">{loginError}</p>
          )}
          <button
            onClick={handleLogin}
            disabled={!keyInput.trim()}
            className="brand-action w-full font-black uppercase tracking-widest py-3 rounded-xl mt-2 disabled:opacity-50 disabled:shadow-none"
          >
            Enter
          </button>
        </div>
      </main>
    )
  }

  return (
    <main className="brand-bg min-h-dvh w-full max-w-6xl mx-auto text-[#23110D] pb-12">
      <div className="brand-sunburst text-white p-4 md:p-6 rounded-b-[1.5rem] md:rounded-b-[2rem] border-b-4 border-[#17120F] shadow-[0_6px_0_#17120F] md:shadow-[0_8px_0_#17120F]">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[10px] font-black tracking-[0.22em] uppercase text-white/80 mb-1">Staff Check-In</p>
            <h1 className="font-display text-xl md:text-2xl uppercase tracking-tight leading-tight drop-shadow-[2px_2px_0_#17120F] break-words">{eventName}</h1>
            <span className="brand-stamp font-brush mt-2 inline-block -rotate-2 rounded-xl px-3 py-0.5 text-sm tracking-[0.12em]">受付中</span>
          </div>
          <div className="hidden sm:block shrink-0">
            <BrandSign compact />
          </div>
        </div>

        {/* Event selector (issue #77) */}
        {events.length > 0 && (
          <select
            value={selectedEvent}
            onChange={e => changeEvent(e.target.value)}
            aria-label="Select event"
            className="mt-3 w-full bg-white border-2 border-[#17120F] text-[#17120F] text-xs font-black rounded-xl px-3 py-2.5 outline-none appearance-none shadow-[3px_3px_0_#17120F]"
          >
            {events.map(ev => (
              <option key={ev.event_name} value={ev.event_name}>
                {formatEventLabel(ev)}
              </option>
            ))}
          </select>
        )}

        <div className="grid grid-cols-3 gap-2 mt-3 md:mt-4 text-[#17120F]">
          <div className="rounded-xl md:rounded-2xl border-2 border-[#17120F] bg-[#FFD51B] p-2 md:p-3 shadow-[3px_3px_0_#17120F]">
            <p className="text-xl md:text-2xl font-black">{pendingCount}</p>
            <p className="text-[9px] uppercase opacity-70 tracking-widest font-black">Pending</p>
          </div>
          <div className="rounded-xl md:rounded-2xl border-2 border-[#17120F] bg-white p-2 md:p-3 shadow-[3px_3px_0_#17120F]">
            <p className="text-xl md:text-2xl font-black">{checkedInCount}</p>
            <p className="text-[9px] uppercase opacity-70 tracking-widest font-black">In</p>
          </div>
          <div className="rounded-xl md:rounded-2xl border-2 border-[#17120F] bg-[#17120F] p-2 md:p-3 text-white shadow-[3px_3px_0_#FFD51B]">
            <p className="text-xl md:text-2xl font-black">{attendingCount}</p>
            <p className="text-[9px] uppercase opacity-70 tracking-widest font-black">People</p>
          </div>
        </div>

        <div className="flex items-center gap-3 mt-3 md:mt-4">
          <p className="text-xs font-black text-white drop-shadow-[1px_1px_0_#17120F]">{checkedInCount} / {attendingCount} in · {waitlistCount} waitlist</p>
          <div className="flex-1" />
          <button
            onClick={scanning ? stopScanner : startScanner}
            className={`min-h-[44px] px-4 py-2 rounded-xl font-black text-xs uppercase tracking-widest cursor-pointer ${scanning ? 'brand-action text-white' : 'brand-action-alt'}`}
          >
            {scanning ? 'Stop' : 'Scan'}
          </button>
        </div>
      </div>

      {/* Filters + search pin to the top so they stay reachable while scrolling a
          long attendee list (the header above scrolls away to free up space). */}
      <div className="sticky top-0 z-20 bg-[#FFF1C2] border-b-2 border-[#17120F]/15 px-4 py-3 space-y-2.5 shadow-[0_6px_10px_-6px_rgba(23,18,15,0.4)] lg:px-6">
        <div className="flex gap-2">
          {(['all', 'pending', 'checked'] as const).map(f => (
            <button
              key={f}
              onClick={() => changeFilter(f)}
              aria-pressed={filter === f}
              className={`min-h-[44px] px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest cursor-pointer border-2 border-[#17120F] ${filter === f ? 'bg-[#17120F] text-white shadow-[3px_3px_0_#FFD51B]' : 'bg-[#FFF8D8] text-[#17120F] shadow-[3px_3px_0_rgba(23,18,15,0.25)]'}`}
            >
              {f}
            </button>
          ))}
        </div>
        <input
          id="attendee-search"
          type="search"
          aria-label="Search attendee"
          placeholder="Search name, drink, guest, #id, @handle..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full border-2 border-[#17120F] rounded-xl px-4 py-3 text-sm font-bold bg-white text-[#17120F] outline-none focus:border-[#E51F1F] shadow-[3px_3px_0_rgba(23,18,15,0.25)]"
        />
      </div>

      <div className="p-4 space-y-4 lg:p-6">
        {/* Scanner — div is always mounted so html5-qrcode can attach to it. */}
        <div className={`brand-card rounded-2xl overflow-hidden ${scanning ? '' : 'hidden'}`}>
          <div id={scannerDivId} className="w-full" />
        </div>

        {/* Attendee list */}
        <div className="space-y-2">
          {filtered.map(a => {
            const name = a.display_name || a.username
            const isIn = !!checkins[a.user_id]
            const checkinTime = isIn ? new Date(checkins[a.user_id].checked_in_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : null
            return (
              <div key={a.user_id} className={`rounded-2xl border-2 border-[#17120F] overflow-hidden shadow-[4px_4px_0_rgba(23,18,15,0.25)] ${isIn ? 'bg-green-50' : 'bg-white'}`}>
                <div className="p-4 flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full border-2 border-[#17120F] flex items-center justify-center font-black text-lg shrink-0 ${isIn ? 'bg-green-100 text-green-800' : 'bg-[#FFD51B] text-[#17120F]'}`}>
                    {isIn ? '✓' : name[0].toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-black text-[#17120F] break-words">
                      {a.attendee_number != null && (
                        <span className="mr-1.5 inline-block rounded-md border-2 border-[#17120F] bg-[#FFD51B] px-1.5 text-[11px] tabular-nums align-middle">#{a.attendee_number}</span>
                      )}
                      {name}
                    </p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {a.drinks.map((d, i) => (
                        <span key={i} className="flex items-center gap-1 text-[9px] font-bold text-[#5B3428] uppercase tracking-wide">
                          <span className={`w-2 h-2 rounded-full shrink-0 ${drinkDot(d)}`} />
                          {d}
                        </span>
                      ))}
                    </div>
                    {a.extra_people > 0 && (
                      <p className="text-[9px] text-[#8B2D1F] mt-0.5">+{a.extra_people} guest{a.extra_people > 1 ? 's' : ''}{a.extras_names.length > 0 ? `: ${a.extras_names.join(', ')}` : ''}</p>
                    )}
                    <p className="mt-1 text-[9px] font-bold uppercase tracking-widest text-[#8B2D1F]/60">@{a.username}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="text-right min-w-[34px]">
                      {isIn ? (
                        <div>
                          <span className="text-[9px] font-black text-green-700 uppercase tracking-widest">In</span>
                          <p className="text-[9px] text-[#8B2D1F]">{checkinTime}</p>
                        </div>
                      ) : (
                        <span className="text-[9px] font-black text-[#8B2D1F]/60 uppercase tracking-widest">Pending</span>
                      )}
                    </div>
                    {/* Manual check-in — always tappable; emphasised when active */}
                    <button
                      onClick={() => manualCheckin(a.user_id)}
                      aria-label={`Check in ${name}`}
                      title="Check in"
                      className={`w-11 h-11 rounded-xl border-2 border-[#17120F] flex items-center justify-center shrink-0 active:translate-x-[1px] active:translate-y-[1px] transition ${isIn ? 'bg-green-600 text-white' : 'bg-[#FFD51B] text-[#17120F]'}`}
                    >
                      <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20 6 9 17l-5-5" />
                      </svg>
                    </button>
                    {/* Manual check-out — always tappable */}
                    <button
                      onClick={() => manualCheckout(a.user_id)}
                      aria-label={`Check out ${name}`}
                      title="Check out"
                      className="w-11 h-11 rounded-xl border-2 border-[#17120F] flex items-center justify-center shrink-0 bg-white text-[#E51F1F] active:translate-x-[1px] active:translate-y-[1px] transition"
                    >
                      <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M18 6 6 18M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
          {filtered.length === 0 && (
            <p className="text-center text-sm font-black text-[#8B2D1F] py-8">No attendees found</p>
          )}
        </div>

        {/* Waitlist section */}
        {attendees.some(a => a.status === 'waitlist') && filter === 'all' && !search && (
          <div className="mt-6">
            <p className="text-[9px] font-black uppercase tracking-widest text-[#8B2D1F] mb-2">Waitlist</p>
            <div className="space-y-2">
              {attendees.filter(a => a.status === 'waitlist').map(a => (
                <div key={a.user_id} className="bg-[#FFD51B] rounded-2xl border-2 border-[#17120F] p-4 flex items-center gap-3 shadow-[4px_4px_0_rgba(23,18,15,0.25)]">
                  <div className="w-8 h-8 rounded-full border-2 border-[#17120F] bg-white flex items-center justify-center font-black text-[#17120F] shrink-0">
                    {(a.display_name || a.username)[0].toUpperCase()}
                  </div>
                  <p className="font-bold text-[#17120F] text-sm">{a.display_name || a.username}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Scan confirmation popup — full-screen so staff instantly see who just
          checked in (and how big their party is), then it auto-dismisses. */}
      {scanResult && (() => {
        const meta = SCAN_RESULT_META[scanResult.kind]
        const party = 1 + (scanResult.extraPeople ?? 0)
        return (
          <div
            role={meta.ok ? 'status' : 'alert'}
            aria-live={meta.ok ? 'polite' : 'assertive'}
            onClick={dismissPopup}
            className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-[#17120F]/70 backdrop-blur-sm cursor-pointer"
          >
            <div className={`brand-card w-full max-w-sm rounded-3xl border-4 border-[#17120F] p-8 text-center ${meta.ok ? 'bg-green-50' : 'bg-red-50'}`}>
              <span className={`mx-auto mb-4 inline-flex h-16 w-16 items-center justify-center rounded-full border-2 border-[#17120F] text-2xl font-black ${meta.ok ? 'bg-[#FFD51B] text-[#17120F]' : 'bg-[#E51F1F] text-white'}`}>
                {meta.ok ? '✓' : '✕'}
              </span>
              <p className={`font-display text-lg uppercase tracking-tight ${meta.ok ? 'text-green-800' : 'text-red-800'}`}>
                {meta.title}
              </p>
              {meta.ok && scanResult.attendeeNumber != null && (
                <span className="mx-auto mt-3 inline-flex items-center gap-1.5 rounded-xl border-2 border-[#17120F] bg-[#FFD51B] px-3 py-1 text-[#17120F] shadow-[2px_2px_0_#17120F]">
                  <span className="text-[9px] font-black uppercase tracking-widest">No.</span>
                  <span className="font-display text-2xl font-black leading-none tabular-nums">{scanResult.attendeeNumber}</span>
                </span>
              )}
              <p className="mt-2 font-black text-3xl leading-tight text-[#17120F] break-words">{scanResult.name}</p>
              {meta.ok && party > 1 && (
                <p className="mt-2 text-sm font-black uppercase tracking-widest text-[#8B2D1F]">
                  Party of {party}{scanResult.extrasNumbers && scanResult.extrasNumbers.length > 0 ? ` · guest no. ${scanResult.extrasNumbers.map(n => `#${n}`).join(' · ')}` : ''}
                </p>
              )}
              {meta.ok && scanResult.extrasNames && scanResult.extrasNames.length > 0 && (
                <p className="mt-1 text-sm font-bold text-[#5B3428]">+{scanResult.extrasNames.join(', ')}</p>
              )}
              {meta.ok && scanResult.time && (
                <p className="mt-3 text-xs font-bold uppercase tracking-widest text-[#8B2D1F]/70">{scanResult.time}</p>
              )}
              <div className="flex justify-center"><LiveClock /></div>
              {scanResult.fromScan && scanResult.kind !== 'error' ? (
                <div className="mt-5">
                  <div className="h-2 w-full overflow-hidden rounded-full border-2 border-[#17120F] bg-white">
                    <div
                      className={`h-full ${meta.ok ? 'bg-[#FFD51B]' : 'bg-[#E51F1F]'}`}
                      style={{ width: `${(popupMsLeft / POPUP_MS[scanResult.kind]) * 100}%` }}
                    />
                  </div>
                  <p className="mt-2 font-mono text-[11px] font-black tabular-nums text-[#8B2D1F]">
                    {Math.ceil(popupMsLeft)} ms · tap to scan next
                  </p>
                </div>
              ) : (
                <p className="mt-5 text-[10px] font-black uppercase tracking-widest text-[#8B2D1F]/50">Tap to dismiss</p>
              )}
            </div>
          </div>
        )
      })()}
    </main>
  )
}
