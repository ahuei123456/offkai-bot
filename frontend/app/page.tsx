'use client'
import { useState, useEffect, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import QRCode from 'react-qr-code'

type ViewState = 'loading' | 'no_token' | 'invalid' | 'not_found' | 'ready'
type AttendeeData = { attendee: Record<string, unknown>; event: Record<string, unknown> }

function getDrinkColors(name: string) {
  const n = name.toLowerCase()
  if (n.includes('oolong'))      return { bg: 'bg-[#F3E8DE]', border: 'border-[#D4BC9E]', strip: 'bg-[#8B5E34]' }
  if (n.includes('cream soda')) return { bg: 'bg-green-50',   border: 'border-green-200',  strip: 'bg-green-500' }
  if (n.includes('coca') || n.includes('coke')) return { bg: 'bg-red-50', border: 'border-red-200', strip: 'bg-red-500' }
  if (n.includes('sapporo') || n.includes('beer')) return { bg: 'bg-amber-50', border: 'border-amber-200', strip: 'bg-amber-400' }
  if (n.includes('highball'))    return { bg: 'bg-orange-50',  border: 'border-orange-200', strip: 'bg-orange-600' }
  if (n.includes('lemon'))       return { bg: 'bg-yellow-50',  border: 'border-yellow-200', strip: 'bg-yellow-400' }
  return { bg: 'bg-gray-50', border: 'border-gray-200', strip: 'bg-[#30364F]' }
}

function formatDateJST(iso: string) {
  try {
    return new Date(iso).toLocaleString('en-GB', {
      timeZone: 'Asia/Tokyo',
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }) + ' JST'
  } catch { return iso }
}

function DrinkCard({ name }: { name: string }) {
  const c = getDrinkColors(name)
  return (
    <div className={`${c.bg} rounded-xl border-2 ${c.border} px-4 py-3 relative overflow-hidden flex items-center gap-3`}>
      <div className={`absolute left-0 top-0 bottom-0 w-2 ${c.strip}`} />
      <span className="font-black text-[#30364F] text-sm pl-2">{name}</span>
    </div>
  )
}

function NoToken() {
  return (
    <main className="min-h-screen bg-[#E1D9BC] flex items-center justify-center p-6 text-[#30364F]">
      <div className="bg-[#F0F0DB] p-8 rounded-3xl border border-[#ACBAC4] shadow-xl w-full max-w-sm text-center">
        <div className="text-5xl mb-6">💬</div>
        <h1 className="text-lg font-black uppercase tracking-widest mb-3">Check Your DMs</h1>
        <p className="text-sm opacity-60 leading-relaxed">
          Your personal event link was sent to you via Discord DM. Open that message and tap the link to view your RSVP details.
        </p>
      </div>
    </main>
  )
}

function InvalidToken({ reason }: { reason: 'invalid' | 'not_found' }) {
  return (
    <main className="min-h-screen bg-[#E1D9BC] flex items-center justify-center p-6 text-[#30364F]">
      <div className="bg-[#F0F0DB] p-8 rounded-3xl border-2 border-red-300 shadow-xl w-full max-w-sm text-center">
        <div className="text-5xl mb-6">{reason === 'not_found' ? '🔍' : '⚠️'}</div>
        <h1 className="text-lg font-black uppercase tracking-widest mb-3">
          {reason === 'not_found' ? 'RSVP Not Found' : 'Link Invalid'}
        </h1>
        <p className="text-sm opacity-60 leading-relaxed">
          {reason === 'not_found'
            ? 'We couldn\'t find your RSVP for this event. Check with the event host if you believe this is an error.'
            : 'This link has expired or is invalid. Check your Discord DMs for an updated link.'}
        </p>
      </div>
    </main>
  )
}

function RSVPCard({ data, token }: { data: AttendeeData; token: string }) {
  const { attendee, event } = data
  const name = (attendee.display_name || attendee.username) as string
  const status = attendee.status as string
  const drinks = (attendee.drinks as string[]) ?? []
  const extraPeople = (attendee.extra_people as number) ?? 0
  const extrasNames = (attendee.extras_names as string[]) ?? []
  const eventName = event.event_name as string
  const venue = event.venue as string
  const address = event.address as string
  const mapsLink = event.google_maps_link as string
  const datetime = event.event_datetime as string
  const isWaitlist = status === 'waitlist'
  const qrValue = typeof window !== 'undefined'
    ? `${window.location.origin}/?token=${token}`
    : `https://chibachan.fadekyun.com/?token=${token}`

  return (
    <main className="min-h-screen bg-[#E1D9BC] text-[#30364F] pb-12 font-sans">
      {/* Header */}
      <div className="bg-[#30364F] text-white p-6 rounded-b-3xl shadow-xl">
        <p className="text-[10px] font-black tracking-[0.2em] uppercase opacity-60 mb-1">Your RSVP</p>
        <h1 className="text-xl font-black uppercase tracking-tight leading-tight">{eventName}</h1>
        <p className="text-xs opacity-50 mt-1">{formatDateJST(datetime)}</p>
      </div>

      <div className="p-6 space-y-4">
        {/* Main identity card */}
        <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-gray-200">
          <div className={`p-3 flex justify-between items-center ${isWaitlist ? 'bg-gradient-to-r from-amber-500 to-amber-400' : 'bg-gradient-to-r from-[#30364F] to-[#4a5578]'}`}>
            <span className="text-[10px] font-black text-white/80 tracking-[0.2em] uppercase">RSVP Status</span>
            <span className={`text-[9px] font-black px-3 py-1 rounded shadow uppercase tracking-widest border ${isWaitlist ? 'bg-white text-amber-700 border-amber-200' : 'bg-[#E1D9BC] text-[#30364F] border-[#30364F]'}`}>
              {isWaitlist ? 'Waitlist' : 'Attending ✓'}
            </span>
          </div>
          <div className="p-6">
            <p className="text-[9px] uppercase font-bold text-gray-400 tracking-wider mb-1">Name</p>
            <h2 className="text-4xl font-black text-[#30364F] uppercase tracking-tighter leading-none mb-6">{name}</h2>

            {extraPeople > 0 && (
              <div className="border-t-2 border-dashed border-gray-200 pt-4">
                <p className="text-[9px] uppercase font-bold text-gray-400 tracking-wider mb-2">
                  +{extraPeople} Guest{extraPeople > 1 ? 's' : ''}
                </p>
                <div className="flex flex-wrap gap-2">
                  {extrasNames.length > 0
                    ? extrasNames.map((n, i) => (
                        <span key={i} className="bg-[#E1D9BC] text-[#30364F] text-xs font-bold px-3 py-1 rounded-full">{n}</span>
                      ))
                    : <span className="text-xs text-gray-400 italic">Names TBD</span>}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Drinks */}
        {drinks.length > 0 && (
          <div className="bg-[#F0F0DB] rounded-2xl border border-[#ACBAC4] p-5">
            <p className="text-[9px] uppercase font-bold text-gray-500 tracking-widest mb-3">
              {drinks.length > 1 ? 'Drink Selections' : 'First Drink'}
            </p>
            <div className="space-y-2">
              {drinks.map((d, i) => <DrinkCard key={i} name={d} />)}
            </div>
          </div>
        )}

        {/* Venue */}
        <div className="bg-[#F0F0DB] rounded-2xl border border-[#ACBAC4] p-5">
          <p className="text-[9px] uppercase font-bold text-gray-500 tracking-widest mb-3">Venue</p>
          <p className="font-black text-[#30364F] text-lg leading-tight">{venue || 'TBA'}</p>
          {address && <p className="text-xs text-gray-500 mt-1">{address}</p>}
          {mapsLink && (
            <a href={mapsLink} target="_blank" rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1 text-[10px] font-bold text-white bg-[#30364F] px-3 py-2 rounded-lg uppercase tracking-wider">
              📍 Open in Maps
            </a>
          )}
        </div>

        {isWaitlist && (
          <div className="bg-amber-50 border-2 border-amber-200 rounded-2xl p-5 text-center">
            <p className="text-amber-800 font-bold text-sm">You&apos;re on the waitlist</p>
            <p className="text-amber-700 text-xs mt-1 opacity-70">You&apos;ll be notified via Discord if a spot opens up.</p>
          </div>
        )}

        {/* QR Code */}
        {!isWaitlist && (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 flex flex-col items-center gap-3">
            <p className="text-[9px] uppercase font-bold text-gray-400 tracking-widest">Entry QR Code</p>
            <div className="p-3 bg-white rounded-xl border border-gray-100">
              <QRCode value={qrValue} size={180} fgColor="#30364F" />
            </div>
            <p className="text-[9px] text-gray-400 text-center">Show this at the door to check in</p>
          </div>
        )}

        <p className="text-center text-[9px] text-gray-400 uppercase tracking-widest pt-2">
          This link is personal — please don&apos;t share it.
        </p>
      </div>
    </main>
  )
}

function AttendeeView() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token')
  const [view, setView] = useState<ViewState>('loading')
  const [data, setData] = useState<AttendeeData | null>(null)

  useEffect(() => {
    if (!token) {
      // Token is absent — schedule the state update asynchronously to avoid a
      // synchronous setState call inside the effect body.
      const id = setTimeout(() => setView('no_token'), 0)
      return () => clearTimeout(id)
    }

    fetch(`/api/attendee?token=${encodeURIComponent(token)}`)
      .then(async r => ({ ok: r.ok, status: r.status, body: await r.json() }))
      .then(({ ok, status, body }) => {
        if (ok) { setData(body); setView('ready') }
        else if (status === 404) setView('not_found')
        else setView('invalid')
      })
      .catch(() => setView('invalid'))
  }, [token])

  if (view === 'loading') return (
    <div className="min-h-screen bg-[#E1D9BC] flex items-center justify-center">
      <div className="text-[#30364F] font-black text-sm uppercase tracking-widest animate-pulse">Loading...</div>
    </div>
  )
  if (view === 'no_token') return <NoToken />
  if (view === 'invalid') return <InvalidToken reason="invalid" />
  if (view === 'not_found') return <InvalidToken reason="not_found" />
  if (view === 'ready' && data) return <RSVPCard data={data} token={token!} />
  return null
}

export default function Page() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-[#E1D9BC] flex items-center justify-center">
        <div className="text-[#30364F] font-black text-sm uppercase tracking-widest">Loading...</div>
      </div>
    }>
      <AttendeeView />
    </Suspense>
  )
}
