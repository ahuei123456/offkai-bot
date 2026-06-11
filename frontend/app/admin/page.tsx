'use client'
import { useState, useEffect, useRef, useCallback } from 'react'
import { flushSync } from 'react-dom'

type Attendee = {
  user_id: number
  username: string
  display_name: string | null
  drinks: string[]
  extra_people: number
  extras_names: string[]
  status: 'attending' | 'waitlist'
}

type CheckinRecord = {
  user_id: number
  event_name: string
  checked_in_at: string
  name: string
}

type EventOption = {
  event_name: string
  event_datetime: string | null
  open: boolean
}

type ScanResult = { ok: boolean; title: string; name: string }

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

export default function AdminPage() {
  const [key, setKey] = useState('')
  const [authed, setAuthed] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [eventName, setEventName] = useState('')
  const [events, setEvents] = useState<EventOption[]>([])
  const [selectedEvent, setSelectedEvent] = useState('')
  const [attendees, setAttendees] = useState<Attendee[]>([])
  const [checkins, setCheckins] = useState<Record<number, CheckinRecord>>({})
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [filter, setFilter] = useState<'all' | 'checked' | 'pending'>('all')
  const [search, setSearch] = useState('')
  // Rows the admin just checked in/out — kept visible regardless of the active
  // filter so a mistaken action can be undone in place (e.g. on the Pending tab).
  const [stickyIds, setStickyIds] = useState<Set<number>>(new Set())

  const scannerRef = useRef<{ stop: () => Promise<void>; clear?: () => void } | null>(null)
  const Html5QrcodeRef = useRef<typeof import('html5-qrcode').Html5Qrcode | null>(null)
  const selectedEventRef = useRef('')
  const keyRef = useRef('')
  const scannerDivId = 'qr-scanner-container'

  // Keep refs in sync so the scan callback always reads current values.
  useEffect(() => { selectedEventRef.current = selectedEvent }, [selectedEvent])
  useEffect(() => { keyRef.current = key }, [key])

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
    if (ok) { setKey(keyInput); setAuthed(true) }
    else alert('Invalid key')
  }

  // Refresh attendee list + check-ins whenever the selected event changes.
  useEffect(() => {
    if (!authed || !selectedEvent) return
    setScanResult(null)
    loadAttendees(key, selectedEvent)
    loadCheckins(key, selectedEvent)
  }, [authed, selectedEvent, key, loadAttendees, loadCheckins])

  // Forget sticky rows when the filter or event changes (fresh view).
  useEffect(() => { setStickyIds(new Set()) }, [filter, selectedEvent])

  // Poll check-ins for the selected event every 10s.
  useEffect(() => {
    if (!authed || !selectedEvent) return
    const id = setInterval(() => loadCheckins(key, selectedEvent), 10_000)
    return () => clearInterval(id)
  }, [authed, selectedEvent, key, loadCheckins])

  // Manual check-in (admin button) — no QR needed, admin is already authed.
  const manualCheckin = useCallback(async (userId: number) => {
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
  const manualCheckout = useCallback(async (userId: number) => {
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
      setScanResult({ ok: false, title: 'Scanner not ready', name: 'Reload the page and try again' })
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

          // Extract the token. Only accept URLs from THIS origin so a malicious
          // QR can't smuggle in a foreign link (and we never navigate to it).
          let token: string | null = null
          try {
            const url = new URL(decodedText)
            if (url.origin !== window.location.origin) {
              setScanResult({ ok: false, title: 'Unrecognised QR', name: 'This code is not from this site' })
              return
            }
            token = url.searchParams.get('token')
          } catch {
            // Not a URL — treat the raw text as the token.
            token = decodedText
          }

          if (!token) {
            setScanResult({ ok: false, title: 'Invalid QR', name: 'No check-in token found' })
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
            setScanResult({
              ok: true,
              title: data.already_checked_in ? 'Already Checked In' : 'Checked In!',
              name: data.record.name || 'Guest',
            })
            setCheckins(prev => ({ ...prev, [data.record.user_id]: data.record }))
          } else if (data.error === 'attendee_not_in_event') {
            setScanResult({ ok: false, title: 'Wrong Event', name: 'Not registered for this event' })
          } else {
            setScanResult({ ok: false, title: 'Invalid', name: 'QR code not recognised' })
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
      setScanResult({
        ok: false,
        title: 'Camera Error',
        name: isPermission
          ? 'Camera blocked. Allow camera access in your browser settings, then reload.'
          : noCamera
            ? 'No camera found on this device.'
            : msg,
      })
    }
  }, [stopScanner])

  const checkedInCount = Object.keys(checkins).length
  const attendingCount = attendees.filter(a => a.status === 'attending').length

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
      const name = (a.display_name || a.username).toLowerCase()
      return name.includes(search.toLowerCase())
    })

  if (!authed) {
    return (
      <main className="min-h-screen bg-[#E1D9BC] flex items-center justify-center p-6">
        <div className="bg-[#F0F0DB] p-8 rounded-3xl border border-[#ACBAC4] shadow-xl w-full max-w-sm">
          <p className="text-[10px] font-black uppercase tracking-widest text-[#30364F] opacity-60 mb-2">Staff Access</p>
          <h1 className="text-xl font-black uppercase text-[#30364F] mb-6">Check-In Admin</h1>
          <input
            type="password"
            placeholder="Admin key"
            value={keyInput}
            onChange={e => setKeyInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
            className="w-full border-2 border-[#ACBAC4] rounded-xl px-4 py-3 text-[#30364F] font-bold bg-white mb-4 outline-none focus:border-[#30364F]"
          />
          <button
            onClick={handleLogin}
            className="w-full bg-[#30364F] text-white font-black uppercase tracking-widest py-3 rounded-xl"
          >
            Enter
          </button>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-[#E1D9BC] text-[#30364F] pb-12">
      {/* Header */}
      <div className="bg-[#30364F] text-white p-6 rounded-b-3xl shadow-xl">
        <p className="text-[10px] font-black tracking-[0.2em] uppercase opacity-60 mb-1">Staff — Check-In</p>
        <h1 className="text-xl font-black uppercase tracking-tight leading-tight">{eventName}</h1>

        {/* Event selector (issue #77) */}
        {events.length > 0 && (
          <select
            value={selectedEvent}
            onChange={e => setSelectedEvent(e.target.value)}
            className="mt-3 w-full bg-white/10 border border-white/30 text-white text-xs font-bold rounded-xl px-3 py-2 outline-none appearance-none"
          >
            {events.map(ev => (
              <option key={ev.event_name} value={ev.event_name} className="text-[#30364F]">
                {formatEventLabel(ev)}
              </option>
            ))}
          </select>
        )}

        <div className="flex gap-4 mt-3 items-center">
          <div className="text-center">
            <p className="text-2xl font-black">{checkedInCount}</p>
            <p className="text-[9px] uppercase opacity-60 tracking-widest">Checked In</p>
          </div>
          <div className="text-white/30 font-thin text-2xl">/</div>
          <div className="text-center">
            <p className="text-2xl font-black">{attendingCount}</p>
            <p className="text-[9px] uppercase opacity-60 tracking-widest">Total</p>
          </div>
          <div className="flex-1" />
          <button
            onClick={scanning ? stopScanner : startScanner}
            className={`px-4 py-2 rounded-xl font-black text-xs uppercase tracking-widest ${scanning ? 'bg-red-500 text-white' : 'bg-[#E1D9BC] text-[#30364F]'}`}
          >
            {scanning ? 'Stop' : '📷 Scan'}
          </button>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Scanner — div is always mounted so html5-qrcode can attach to it. */}
        <div className={`bg-white rounded-2xl border border-gray-200 overflow-hidden ${!scanning && !scanResult ? 'hidden' : ''}`}>
          <div id={scannerDivId} className={`w-full ${scanning ? '' : 'hidden'}`} />
          {!scanning && scanResult && (
            <div className={`p-6 text-center ${scanResult.ok ? 'bg-green-50' : 'bg-red-50'}`}>
              <div className="text-4xl mb-2">{scanResult.ok ? (scanResult.title === 'Already Checked In' ? '🔄' : '✅') : '❌'}</div>
              <p className={`font-black text-lg uppercase ${scanResult.ok ? 'text-green-700' : 'text-red-700'}`}>
                {scanResult.title}
              </p>
              <p className="font-bold text-sm mt-1 text-gray-600">{scanResult.name}</p>
              <button
                onClick={startScanner}
                className="mt-4 bg-[#30364F] text-white font-black uppercase text-xs tracking-widest px-6 py-2 rounded-xl"
              >
                Scan Next
              </button>
            </div>
          )}
        </div>

        {/* Filters + Search */}
        <div className="flex gap-2">
          {(['all', 'pending', 'checked'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest ${filter === f ? 'bg-[#30364F] text-white' : 'bg-[#F0F0DB] text-[#30364F] border border-[#ACBAC4]'}`}
            >
              {f}
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder="Search name..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full border-2 border-[#ACBAC4] rounded-xl px-4 py-2.5 text-sm font-bold bg-white text-[#30364F] outline-none focus:border-[#30364F]"
        />

        {/* Attendee list */}
        <div className="space-y-2">
          {filtered.map(a => {
            const name = a.display_name || a.username
            const isIn = !!checkins[a.user_id]
            const checkinTime = isIn ? new Date(checkins[a.user_id].checked_in_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : null
            return (
              <div key={a.user_id} className={`bg-white rounded-2xl border-2 overflow-hidden ${isIn ? 'border-green-300' : 'border-gray-200'}`}>
                <div className="p-4 flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center font-black text-lg shrink-0 ${isIn ? 'bg-green-100 text-green-700' : 'bg-[#E1D9BC] text-[#30364F]'}`}>
                    {isIn ? '✓' : name[0].toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-black text-[#30364F] truncate">{name}</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {a.drinks.map((d, i) => (
                        <span key={i} className="flex items-center gap-1 text-[9px] font-bold text-gray-500 uppercase tracking-wide">
                          <span className={`w-2 h-2 rounded-full shrink-0 ${drinkDot(d)}`} />
                          {d}
                        </span>
                      ))}
                    </div>
                    {a.extra_people > 0 && (
                      <p className="text-[9px] text-gray-400 mt-0.5">+{a.extra_people} guest{a.extra_people > 1 ? 's' : ''}{a.extras_names.length > 0 ? `: ${a.extras_names.join(', ')}` : ''}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="text-right min-w-[34px]">
                      {isIn ? (
                        <div>
                          <span className="text-[9px] font-black text-green-600 uppercase tracking-widest">In</span>
                          <p className="text-[9px] text-gray-400">{checkinTime}</p>
                        </div>
                      ) : (
                        <span className="text-[9px] font-black text-gray-300 uppercase tracking-widest">Pending</span>
                      )}
                    </div>
                    {/* Manual check-in — always tappable; emphasised when active */}
                    <button
                      onClick={() => manualCheckin(a.user_id)}
                      aria-label={`Check in ${name}`}
                      title="Check in"
                      className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 active:scale-95 transition ${isIn ? 'bg-green-600 text-white' : 'bg-green-100 text-green-700 active:bg-green-200'}`}
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
                      className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-red-100 text-red-700 active:bg-red-200 active:scale-95 transition"
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
            <p className="text-center text-sm text-gray-400 py-8">No attendees found</p>
          )}
        </div>

        {/* Waitlist section */}
        {attendees.some(a => a.status === 'waitlist') && filter === 'all' && !search && (
          <div className="mt-6">
            <p className="text-[9px] font-black uppercase tracking-widest text-gray-400 mb-2">Waitlist</p>
            <div className="space-y-2">
              {attendees.filter(a => a.status === 'waitlist').map(a => (
                <div key={a.user_id} className="bg-amber-50 rounded-2xl border border-amber-200 p-4 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center font-black text-amber-700 shrink-0">
                    {(a.display_name || a.username)[0].toUpperCase()}
                  </div>
                  <p className="font-bold text-amber-800 text-sm">{a.display_name || a.username}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
