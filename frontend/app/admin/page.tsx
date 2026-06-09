'use client'
import { useState, useEffect, useRef, useCallback } from 'react'

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

export default function AdminPage() {
  const [key, setKey] = useState('')
  const [authed, setAuthed] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [eventName, setEventName] = useState('')
  const [attendees, setAttendees] = useState<Attendee[]>([])
  const [checkins, setCheckins] = useState<Record<number, CheckinRecord>>({})
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<{ ok: boolean; name: string; already: boolean } | null>(null)
  const [filter, setFilter] = useState<'all' | 'checked' | 'pending'>('all')
  const [search, setSearch] = useState('')
  const scannerRef = useRef<unknown>(null)
  const scannerDivId = 'qr-scanner-container'

  const fetchData = useCallback(async (adminKey: string) => {
    const [attendeesRes, checkinsRes] = await Promise.all([
      fetch(`/api/attendees?key=${adminKey}`),
      fetch(`/api/checkin?key=${adminKey}`),
    ])
    if (!attendeesRes.ok) return false
    const { event_name, attendees: att } = await attendeesRes.json()
    const chk: CheckinRecord[] = checkinsRes.ok ? await checkinsRes.json() : []
    setEventName(event_name)
    setAttendees(att)
    setCheckins(Object.fromEntries(chk.map((c: CheckinRecord) => [c.user_id, c])))
    return true
  }, [])

  const handleLogin = async () => {
    const ok = await fetchData(keyInput)
    if (ok) { setKey(keyInput); setAuthed(true) }
    else alert('Invalid key')
  }

  // Poll checkins every 10s
  useEffect(() => {
    if (!authed) return
    const id = setInterval(() => {
      fetch(`/api/checkin?key=${key}`)
        .then(r => r.ok ? r.json() : [])
        .then((chk: CheckinRecord[]) => setCheckins(Object.fromEntries(chk.map((c: CheckinRecord) => [c.user_id, c]))))
    }, 10_000)
    return () => clearInterval(id)
  }, [authed, key])

  const startScanner = useCallback(async () => {
    const { Html5Qrcode } = await import('html5-qrcode')
    const scanner = new Html5Qrcode(scannerDivId)
    scannerRef.current = scanner
    setScanning(true)
    setScanResult(null)

    await scanner.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: { width: 250, height: 250 } },
      async (decodedText) => {
        await scanner.stop()
        setScanning(false)

        // Extract token from URL or use raw value
        let token = decodedText
        try {
          const url = new URL(decodedText)
          token = url.searchParams.get('token') || decodedText
        } catch { /* not a URL */ }

        const res = await fetch('/api/checkin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        })
        const data = await res.json()

        if (res.ok) {
          const name = data.record?.name || 'Guest'
          setScanResult({ ok: true, name, already: !!data.already_checked_in })
          setCheckins(prev => ({ ...prev, [data.record.user_id]: data.record }))
        } else {
          setScanResult({ ok: false, name: 'Invalid QR code', already: false })
        }
      },
      () => { /* ignore scan errors */ }
    )
  }, [])

  const stopScanner = useCallback(async () => {
    if (scannerRef.current) {
      try { await (scannerRef.current as { stop: () => Promise<void> }).stop() } catch { /* ignore */ }
      scannerRef.current = null
    }
    setScanning(false)
  }, [])

  const checkedInCount = Object.keys(checkins).length
  const attendingCount = attendees.filter(a => a.status === 'attending').length

  const filtered = attendees
    .filter(a => a.status === 'attending')
    .filter(a => {
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
        <div className="flex gap-4 mt-3">
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
        {/* Scanner */}
        {(scanning || scanResult) && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            {scanning && (
              <div id={scannerDivId} className="w-full" />
            )}
            {!scanning && scanResult && (
              <div className={`p-6 text-center ${scanResult.ok ? 'bg-green-50' : 'bg-red-50'}`}>
                <div className="text-4xl mb-2">{scanResult.ok ? (scanResult.already ? '🔄' : '✅') : '❌'}</div>
                <p className={`font-black text-lg uppercase ${scanResult.ok ? 'text-green-700' : 'text-red-700'}`}>
                  {scanResult.already ? 'Already Checked In' : scanResult.ok ? 'Checked In!' : 'Invalid'}
                </p>
                <p className="font-bold text-sm mt-1 text-gray-600">{scanResult.name}</p>
                <button
                  onClick={() => { setScanResult(null); startScanner() }}
                  className="mt-4 bg-[#30364F] text-white font-black uppercase text-xs tracking-widest px-6 py-2 rounded-xl"
                >
                  Scan Next
                </button>
              </div>
            )}
          </div>
        )}

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
                  <div className="text-right shrink-0">
                    {isIn ? (
                      <div>
                        <span className="text-[9px] font-black text-green-600 uppercase tracking-widest">In</span>
                        <p className="text-[9px] text-gray-400">{checkinTime}</p>
                      </div>
                    ) : (
                      <span className="text-[9px] font-black text-gray-300 uppercase tracking-widest">Pending</span>
                    )}
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
