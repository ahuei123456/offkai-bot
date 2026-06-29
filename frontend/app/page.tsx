'use client'
import { useState, useEffect, useRef, useCallback, useSyncExternalStore, Suspense, createContext, useContext } from 'react'
import { useSearchParams } from 'next/navigation'
import QRCode from 'react-qr-code'

type ViewState = 'loading' | 'no_token' | 'invalid' | 'not_found' | 'unavailable' | 'ready'
type AttendeeData = { attendee: Record<string, unknown>; event: Record<string, unknown> }

type Lang = 'en' | 'ja'

const STRINGS = {
  en: {
    locale: 'en-GB',
    rsvpPass: 'RSVP Pass',
    loading: 'Loading...',
    checkDms: 'Check Your DMs',
    checkDmsBody: 'Your personal event link was sent to you via Discord DM. Open that message and tap the link to view your RSVP details.',
    linkInvalid: 'Link Invalid',
    rsvpNotFound: 'RSVP Not Found',
    rsvpUnavailable: 'RSVP Unavailable',
    notFoundBody: "We couldn't find your RSVP for this event. Check with the event host if you believe this is an error.",
    unavailableBody: "We couldn't load your RSVP right now. Check your connection and try again.",
    invalidBody: 'This link has expired or is invalid. Check your Discord DMs for an updated link.',
    retry: 'Retry',
    offkaiPass: 'Offkai Pass',
    today: 'Today',
    arrival: 'Arrival',
    entryPass: 'Entry Pass',
    waitlist: 'Waitlist',
    confirmed: 'Confirmed',
    name: 'Name',
    entryNo: 'Entry No.',
    guestNos: 'Guest no.',
    showAtCheckin: 'Show at check-in',
    live: 'Live',
    standbyMode: 'Standby Mode',
    standbyBody: "You're on the waitlist — we'll DM you on Discord if a spot opens up.",
    venue: 'Venue',
    maps: 'Maps',
    drinkTickets: 'Drink Tickets',
    firstDrinkTicket: 'First Drink Ticket',
    readyCheck: 'Ready Check',
    chkEntry: 'Entry pass',
    chkRules: 'Rules',
    chkArrival: 'Arrival',
    offkaiDetails: 'Offkai Details',
    capacity: 'Capacity',
    rsvp: 'RSVP',
    deadline: 'Deadline',
    personalLink: "This link is personal — please don't share it.",
    open: 'Open',
    closed: 'Closed',
    tbd: 'TBD',
    tba: 'TBA',
    solo: 'Solo',
    partyOf: (n: number) => `Party of ${n}`,
    guests: (n: number) => `+${n} guest${n > 1 ? 's' : ''}`,
    datePending: 'Date pending',
    startsOn: (d: string) => `Starts ${d}`,
    startsIn: (m: number) => `Starts in ${m} min`,
    happeningNow: 'Happening now',
    eventEnded: 'Event ended',
  },
  ja: {
    locale: 'ja-JP',
    rsvpPass: '参加パス',
    loading: '読み込み中...',
    checkDms: 'DMをご確認ください',
    checkDmsBody: '個別の参加リンクをDiscordのDMでお送りしました。そのメッセージを開き、リンクをタップして参加情報をご確認ください。',
    linkInvalid: 'リンクが無効です',
    rsvpNotFound: '参加情報が見つかりません',
    rsvpUnavailable: '参加情報を取得できません',
    notFoundBody: 'このイベントの参加情報が見つかりませんでした。お心当たりがない場合は主催者にお問い合わせください。',
    unavailableBody: '現在、参加情報を読み込めませんでした。接続を確認して再度お試しください。',
    invalidBody: 'このリンクは期限切れか無効です。最新のリンクはDiscordのDMをご確認ください。',
    retry: '再試行',
    offkaiPass: 'オフ会パス',
    today: '本日',
    arrival: '到着',
    entryPass: '入場パス',
    waitlist: 'キャンセル待ち',
    confirmed: '確定',
    name: 'お名前',
    entryNo: '受付番号',
    guestNos: '同伴番号',
    showAtCheckin: '受付でご提示ください',
    live: 'ライブ',
    standbyMode: 'キャンセル待ち',
    standbyBody: 'キャンセル待ちです。空きが出たらDiscordのDMでお知らせします。',
    venue: '会場',
    maps: '地図',
    drinkTickets: 'ドリンクチケット',
    firstDrinkTicket: '1杯目ドリンクチケット',
    readyCheck: '準備確認',
    chkEntry: '入場',
    chkRules: 'ルール',
    chkArrival: '到着',
    offkaiDetails: 'オフ会詳細',
    capacity: '定員',
    rsvp: '受付',
    deadline: '締切',
    personalLink: 'このリンクは個人用です。共有しないでください。',
    open: '受付中',
    closed: '締切',
    tbd: '未定',
    tba: '未定',
    solo: '1名',
    partyOf: (n: number) => `${n}名`,
    guests: (n: number) => `同伴${n}名`,
    datePending: '日程未定',
    startsOn: (d: string) => `${d} 開始`,
    startsIn: (m: number) => `あと${m}分`,
    happeningNow: '開催中',
    eventEnded: '終了',
  },
}

type Strings = typeof STRINGS['en']

const LangContext = createContext<{ lang: Lang; t: Strings; setLang: (l: Lang) => void }>({
  lang: 'en', t: STRINGS.en, setLang: () => {},
})
const useT = () => useContext(LangContext)

const LANG_EVENT = 'offkai-lang-change'

function subscribeLang(cb: () => void) {
  window.addEventListener(LANG_EVENT, cb)
  window.addEventListener('storage', cb)
  return () => {
    window.removeEventListener(LANG_EVENT, cb)
    window.removeEventListener('storage', cb)
  }
}

// Reads the saved choice, else falls back to the browser locale. Used as the
// useSyncExternalStore client snapshot so language resolves on the client
// without a hydration mismatch (server always snapshots 'en').
function readLang(): Lang {
  const saved = localStorage.getItem('lang')
  if (saved === 'en' || saved === 'ja') return saved
  return navigator.language?.toLowerCase().startsWith('ja') ? 'ja' : 'en'
}

function useLang(): [Lang, (l: Lang) => void] {
  const lang = useSyncExternalStore(subscribeLang, readLang, () => 'en' as Lang)
  const setLang = useCallback((l: Lang) => {
    localStorage.setItem('lang', l)
    window.dispatchEvent(new Event(LANG_EVENT))
  }, [])
  return [lang, setLang]
}

function LangToggle({ className = '' }: { className?: string }) {
  const { lang, setLang } = useT()
  return (
    <div className={`inline-flex shrink-0 overflow-hidden rounded-lg border-2 border-[#17120F] text-[10px] font-black uppercase tracking-widest shadow-[2px_2px_0_#17120F] ${className}`}>
      {(['en', 'ja'] as const).map(l => (
        <button
          key={l}
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={`inline-flex min-h-[44px] items-center justify-center px-4 ${lang === l ? 'bg-[#17120F] text-white' : 'bg-white text-[#17120F]'}`}
        >
          {l === 'en' ? 'EN' : '日本語'}
        </button>
      ))}
    </div>
  )
}

function getDrinkColors(name: string) {
  const n = name.toLowerCase()
  if (n.includes('oolong'))      return { bg: 'bg-[#F3E8DE]', border: 'border-[#D4BC9E]', strip: 'bg-[#8B5E34]' }
  if (n.includes('cream soda')) return { bg: 'bg-green-50',   border: 'border-green-200',  strip: 'bg-green-500' }
  if (n.includes('coca') || n.includes('coke')) return { bg: 'bg-red-50', border: 'border-red-200', strip: 'bg-red-500' }
  if (n.includes('sapporo') || n.includes('beer')) return { bg: 'bg-amber-50', border: 'border-amber-200', strip: 'bg-amber-400' }
  if (n.includes('highball'))    return { bg: 'bg-orange-50',  border: 'border-orange-200', strip: 'bg-orange-600' }
  if (n.includes('lemon'))       return { bg: 'bg-yellow-50',  border: 'border-yellow-200', strip: 'bg-yellow-400' }
  return { bg: 'bg-white', border: 'border-[#17120F]', strip: 'bg-[#17120F]' }
}

function formatArrivalTime(iso: string, t: Strings) {
  if (!iso) return t.tbd
  try {
    return new Date(iso).toLocaleTimeString('en-GB', {
      timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit',
    }) + ' JST'
  } catch { return t.tbd }
}

function getEventPhase(iso: string, t: Strings) {
  if (!iso) return t.datePending
  const eventTime = new Date(iso).getTime()
  if (Number.isNaN(eventTime)) return t.datePending
  const diffMinutes = Math.round((eventTime - Date.now()) / 60000)
  if (diffMinutes > 90) return t.startsOn(new Date(iso).toLocaleDateString(t.locale, { timeZone: 'Asia/Tokyo', month: 'short', day: 'numeric' }))
  if (diffMinutes > 0) return t.startsIn(diffMinutes)
  if (diffMinutes > -180) return t.happeningNow
  return t.eventEnded
}

function DrinkCard({ name }: { name: string }) {
  const c = getDrinkColors(name)
  return (
    <div className={`${c.bg} rounded-xl border-2 ${c.border} px-4 py-3 relative overflow-hidden flex items-center gap-3 shadow-[3px_3px_0_#17120F]`}>
      <div className={`absolute left-0 top-0 bottom-0 w-2 ${c.strip}`} />
      <span className="font-black text-[#23110D] text-sm pl-2">{name}</span>
    </div>
  )
}

function Lantern({ className = '', delay = '0s', variant = 'red', glyph = '祭' }: { className?: string; delay?: string; variant?: 'red' | 'gold'; glyph?: string }) {
  const body = variant === 'gold' ? '#FFC400' : '#E51F1F'
  const glyphFill = variant === 'gold' ? '#9A1414' : '#FFF8D8'
  return (
    <svg
      viewBox="0 0 44 74"
      className={className}
      style={{ transformOrigin: 'top center', animation: 'lanternSway 3.4s ease-in-out infinite', animationDelay: delay }}
      aria-hidden="true"
    >
      <line x1="22" y1="0" x2="22" y2="8" stroke="#17120F" strokeWidth="2" />
      <rect x="11" y="7" width="22" height="7" rx="2.5" fill="#3A2A1A" stroke="#17120F" strokeWidth="2" />
      <ellipse cx="22" cy="35" rx="18" ry="21" fill={body} stroke="#17120F" strokeWidth="2.5" />
      <ellipse cx="15" cy="29" rx="4" ry="8" fill="#FFFFFF" opacity="0.22" />
      <g stroke="#17120F" strokeOpacity="0.32" strokeWidth="1.5" fill="none">
        <path d="M5.5 27 Q22 24 38.5 27" />
        <path d="M4 35 Q22 32 40 35" />
        <path d="M5.5 43 Q22 46 38.5 43" />
      </g>
      <text x="22" y="41" textAnchor="middle" fontSize="18" fontWeight="700" fill={glyphFill} style={{ fontFamily: "'Hiragino Kaku Gothic ProN','Yu Gothic',sans-serif" }}>{glyph}</text>
      <rect x="14" y="54" width="16" height="6" rx="2" fill="#3A2A1A" stroke="#17120F" strokeWidth="2" />
      <g stroke="#FFC400" strokeWidth="2" strokeLinecap="round">
        <line x1="18" y1="60" x2="17" y2="71" /><line x1="22" y1="60" x2="22" y2="72" /><line x1="26" y1="60" x2="27" y2="71" />
      </g>
    </svg>
  )
}

function LanternGarland() {
  const lanterns = [
    { g: '大', v: 'red' }, { g: '衆', v: 'gold' }, { g: '酒', v: 'red' }, { g: '場', v: 'gold' },
    { g: '乾', v: 'red' }, { g: '杯', v: 'gold' }, { g: '祭', v: 'red' },
  ] as const
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 px-1.5" aria-hidden="true">
      <div className="absolute left-2 right-2 top-1.5 h-0.5 rounded-full bg-[#17120F]/70" />
      <div className="relative flex items-start justify-between">
        {lanterns.map((l, i) => (
          <Lantern key={i} variant={l.v} glyph={l.g} delay={`${i * 0.22}s`} className={i % 2 ? 'h-9' : 'h-[2.9rem]'} />
        ))}
      </div>
    </div>
  )
}

function KaraagePiece({ x, y, s = 1, rot = 0 }: { x: number; y: number; s?: number; rot?: number }) {
  return (
    <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${s})`}>
      <path
        d="M0 -13 C5 -13 7 -10 9 -9 C13 -9 14 -5 13 -2 C15 2 13 6 10 7 C9 11 5 13 1 11 C-3 13 -8 11 -8 7 C-12 6 -13 1 -11 -3 C-13 -7 -9 -11 -5 -10 C-4 -12 -2 -13 0 -13 Z"
        fill="#C36A18" stroke="#17120F" strokeWidth="2.2" strokeLinejoin="round"
      />
      <path d="M-5 -6 C-1 -8 4 -7 5 -3 C6 0 3 3 -1 2 C-5 2 -7 -3 -5 -6 Z" fill="#E89A40" />
      <circle cx="4" cy="5" r="1.2" fill="#3A2410" />
      <circle cx="-3" cy="6" r="1" fill="#3A2410" />
      <circle cx="6" cy="-2" r="0.9" fill="#3A2410" />
    </g>
  )
}

function KaraageBoat({ className = '' }: { className?: string }) {
  const pieces = [
    { x: 46, y: 98, s: 1, rot: -8 }, { x: 72, y: 104, s: 1.1, rot: 12 }, { x: 102, y: 106, s: 1.18, rot: -4 },
    { x: 134, y: 104, s: 1.1, rot: 14 }, { x: 162, y: 98, s: 1, rot: -10 },
    { x: 60, y: 84, s: 1, rot: 18 }, { x: 90, y: 86, s: 1.05, rot: -14 }, { x: 120, y: 86, s: 1.05, rot: 8 }, { x: 150, y: 84, s: 1, rot: -18 },
    { x: 78, y: 68, s: 0.95, rot: -6 }, { x: 108, y: 68, s: 1, rot: 12 }, { x: 136, y: 68, s: 0.95, rot: -12 },
    { x: 94, y: 56, s: 0.92, rot: 8 }, { x: 122, y: 56, s: 0.92, rot: -8 }, { x: 108, y: 46, s: 0.85, rot: 2 },
  ]
  const negi = [
    { x: 72, y: 40 }, { x: 80, y: 24 }, { x: 86, y: 14 }, { x: 92, y: 8 }, { x: 98, y: 4, green: true }, { x: 103, y: 12 },
    { x: 108, y: 2 }, { x: 113, y: 8, green: true }, { x: 118, y: 0 }, { x: 123, y: 8 }, { x: 128, y: 2 },
    { x: 133, y: 10, green: true }, { x: 138, y: 4 }, { x: 144, y: 14 }, { x: 150, y: 22, green: true }, { x: 158, y: 36 },
    { x: 100, y: 16 }, { x: 114, y: 14 }, { x: 128, y: 18 }, { x: 66, y: 30 },
  ]
  return (
    <svg viewBox="0 0 240 168" className={className} aria-hidden="true">
      <g stroke="#FFFFFF" strokeWidth="3" strokeLinecap="round" fill="none" opacity="0.6">
        <path d="M84 14 q-7 -9 0 -17 q5 -6 0 -12" /><path d="M120 8 q-7 -9 0 -17 q5 -6 0 -12" /><path d="M156 16 q-7 -9 0 -17 q5 -6 0 -12" />
      </g>
      <g strokeLinecap="round" strokeWidth="3.6">
        {negi.map((n, i) => (
          <line key={i} x1="115" y1="56" x2={n.x} y2={n.y} stroke={n.green ? '#7FB84A' : '#FCFCF7'} />
        ))}
      </g>
      <path d="M88 54 Q104 40 120 44 Q138 39 152 54 Q138 62 120 60 Q100 63 88 54 Z" fill="#FCFCF7" stroke="#17120F" strokeWidth="1.6" strokeLinejoin="round" />
      {pieces.map((p, i) => <KaraagePiece key={i} {...p} />)}
      <g stroke="#17120F" strokeWidth="2" strokeLinejoin="round">
        <path d="M40 102 a15 15 0 0 1 15 15 l-15 0 z" fill="#FFE34D" />
        <path d="M40 102 a15 15 0 0 1 15 15" fill="none" stroke="#E8C200" strokeWidth="2" />
        <path d="M196 102 a15 15 0 0 0 -15 15 l15 0 z" fill="#FFE34D" />
      </g>
      <path d="M6 108 Q120 99 234 108 L210 130 Q120 152 30 130 Z" fill="#A9743C" stroke="#17120F" strokeWidth="2.6" strokeLinejoin="round" />
      <path d="M6 108 Q120 99 234 108 L228 113 Q120 105 12 113 Z" fill="#C28E50" stroke="#17120F" strokeWidth="1.5" />
      <path d="M26 118 Q120 130 214 118" fill="none" stroke="#6B4521" strokeWidth="2.4" strokeLinecap="round" />
      <g stroke="#6B4521" strokeWidth="1.4" strokeOpacity="0.55" strokeLinecap="round">
        <line x1="60" y1="124" x2="60" y2="134" /><line x1="100" y1="128" x2="100" y2="139" />
        <line x1="140" y1="128" x2="140" y2="139" /><line x1="180" y1="124" x2="180" y2="134" />
      </g>
    </svg>
  )
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

function BrandSign({ compact = false }: { compact?: boolean }) {
  const { t } = useT()
  if (compact) {
    return (
      <div className="inline-flex items-center gap-1.5">
        <SmileyMark className="h-7 w-7 shrink-0 -rotate-6" />
        <span className="brand-wordmark text-2xl leading-none">Offkai Bot</span>
      </div>
    )
  }
  return (
    <div className="inline-flex flex-col items-center px-2">
      <span className="brand-banner inline-block rounded-lg px-3 py-0.5 text-[11px] tracking-[0.34em]">大衆酒場</span>
      <div className="mt-2 flex items-center gap-1.5">
        <span className="brand-wordmark text-[2.4rem] leading-[0.95]">Offkai Bot</span>
        <SmileyMark className="h-8 w-8 shrink-0 -rotate-6 drop-shadow-[2px_2px_0_#17120F]" />
      </div>
      <span className="mt-2 font-display text-[10px] uppercase tracking-[0.42em] text-white drop-shadow-[1.5px_1.5px_0_#17120F]">{t.rsvpPass}</span>
    </div>
  )
}

function CenterCard({ children }: { children: React.ReactNode }) {
  return (
    <main className="brand-rays min-h-dvh flex flex-col items-center justify-center p-6 text-[#23110D]">
      <div className="mb-4 w-full max-w-sm flex justify-end">
        <LangToggle />
      </div>
      <div className="brand-card w-full max-w-sm rounded-3xl p-7 text-center">
        {children}
      </div>
    </main>
  )
}

function NoToken() {
  const { t } = useT()
  return (
    <CenterCard>
      <BrandSign compact />
      <h1 className="mt-7 font-display text-2xl uppercase tracking-tight">{t.checkDms}</h1>
      <p className="mt-3 text-sm font-bold leading-relaxed text-[#5B3428]">{t.checkDmsBody}</p>
    </CenterCard>
  )
}

function InvalidToken({ reason }: { reason: 'invalid' | 'not_found' | 'unavailable' }) {
  const { t } = useT()
  const title = reason === 'not_found' ? t.rsvpNotFound : reason === 'unavailable' ? t.rsvpUnavailable : t.linkInvalid
  const badge = reason === 'not_found' ? '404' : reason === 'unavailable' ? '503' : 'NG'
  const message =
    reason === 'not_found' ? t.notFoundBody
      : reason === 'unavailable' ? t.unavailableBody
        : t.invalidBody
  return (
    <CenterCard>
      <BrandSign compact />
      <p className="mx-auto mt-7 inline-flex h-12 min-w-12 items-center justify-center rounded-full border-2 border-[#17120F] bg-[#E51F1F] px-4 text-sm font-black uppercase tracking-widest text-white">
        {badge}
      </p>
      <h1 className="mt-4 font-display text-2xl uppercase tracking-tight">{title}</h1>
      <p className="mt-3 text-sm font-bold leading-relaxed text-[#5B3428]">{message}</p>
      {reason === 'unavailable' && (
        <button
          onClick={() => window.location.reload()}
          className="brand-action mt-5 min-h-[44px] rounded-xl px-6 font-black uppercase tracking-widest text-sm"
        >
          {t.retry}
        </button>
      )}
    </CenterCard>
  )
}

// Cached JST formatter so the rAF loop allocates nothing per frame.
const JST_HMS = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Tokyo', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
})

// Live JST clock with milliseconds under the QR — it visibly ticks, so staff
// can tell a real pass from a screenshot. Writes textContent via a ref (no React
// state) so it never re-renders the pass while ticking.
function LiveClock() {
  const { t } = useT()
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
    <div className="flex items-center justify-center gap-2 rounded-xl border-2 border-[#17120F] bg-[#17120F] px-3 py-1.5 shadow-[3px_3px_0_#E51F1F]">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-[#3CCB5A]" aria-hidden="true" />
      <span className="text-[9px] font-black uppercase tracking-[0.2em] text-[#FFD51B]">{t.live}</span>
      <span ref={ref} className="font-mono text-sm font-black tabular-nums text-white" suppressHydrationWarning>--:--:--.--- JST</span>
    </div>
  )
}

function RSVPCard({ data, token }: { data: AttendeeData; token: string }) {
  const { t } = useT()
  const { attendee, event } = data
  const name = (attendee.display_name || attendee.username) as string
  const status = attendee.status as string
  const drinks = (attendee.drinks as string[]) ?? []
  const extraPeople = (attendee.extra_people as number) ?? 0
  const extrasNames = (attendee.extras_names as string[]) ?? []
  const attendeeNumber = (attendee.attendee_number as number | null) ?? null
  const extrasNumbers = (attendee.extras_attendee_numbers as number[]) ?? []
  const behaviorConfirmed = !!attendee.behavior_confirmed
  const arrivalConfirmed = !!attendee.arrival_confirmed
  const eventName = event.event_name as string
  const venue = (event.venue as string) || t.tba
  const address = (event.address as string) || ''
  const mapsLink = (event.google_maps_link as string) || ''
  const datetime = (event.event_datetime as string) || ''
  const maxCapacity = event.max_capacity as number | undefined
  const eventOpen = event.open as boolean | undefined
  const eventDeadline = event.event_deadline as string | undefined
  const isWaitlist = status === 'waitlist'
  const partySize = 1 + extraPeople
  const companions = extrasNames.length > 0 ? extrasNames.join(', ') : extraPeople > 0 ? t.guests(extraPeople) : t.solo
  const rsvpStatus = typeof eventOpen === 'boolean' ? (eventOpen ? t.open : t.closed) : t.tbd
  const checks = [
    { label: t.chkEntry, done: !isWaitlist },
    { label: t.chkRules, done: behaviorConfirmed },
    { label: t.chkArrival, done: arrivalConfirmed },
  ]
  const qrValue = typeof window !== 'undefined'
    ? `${window.location.origin}/?token=${token}`
    : `/?token=${token}`

  return (
    <main className="brand-bg min-h-dvh w-full max-w-md mx-auto text-[#23110D] pb-12 font-sans md:my-8 md:min-h-0 md:rounded-[2rem] md:shadow-2xl md:overflow-hidden">
      <div className="brand-sunburst relative overflow-hidden px-5 pb-5 pt-16 text-white rounded-b-[2rem] border-b-4 border-[#17120F] shadow-[0_8px_0_#17120F]">
        <LanternGarland />

        <div className="absolute right-4 top-4 z-10">
          <LangToggle />
        </div>

        <div className="flex justify-center">
          <BrandSign />
        </div>

        <div className="relative mt-1 flex justify-center">
          <KaraageBoat className="h-36 w-auto drop-shadow-[3px_4px_0_rgba(23,18,15,0.22)]" />
          <span className="brand-stamp font-brush absolute -left-1 bottom-3 -rotate-6 rounded-xl px-3 py-1 text-sm tracking-[0.12em]">バカ盛り</span>
        </div>

        <div className="mt-3 flex flex-col items-center text-center">
          <div className="brand-banner inline-block rounded-xl px-4 py-1.5">
            <h1 className="font-display text-lg sm:text-xl uppercase tracking-tight leading-tight text-[#FFF8D8]">{eventName}</h1>
          </div>
          <span className="mt-2 inline-block rounded-xl border-2 border-[#17120F] bg-white px-3 py-1 text-[10px] font-black uppercase tracking-widest text-[#17120F] shadow-[3px_3px_0_#FFD51B]">{t.offkaiPass}</span>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-2 text-[#23110D]">
          <div className="rounded-2xl border-2 border-[#17120F] bg-[#FFD51B] p-3 shadow-[3px_3px_0_#17120F]">
            <p className="text-[9px] font-black uppercase tracking-widest opacity-70">{t.today}</p>
            <p className="text-sm font-black">{getEventPhase(datetime, t)}</p>
          </div>
          <div className="rounded-2xl border-2 border-[#17120F] bg-white p-3 shadow-[3px_3px_0_#17120F]">
            <p className="text-[9px] font-black uppercase tracking-widest opacity-70">{t.arrival}</p>
            <p className="text-sm font-black">{formatArrivalTime(datetime, t)}</p>
          </div>
        </div>
      </div>

      <div className="p-6 space-y-4">
        <div className="brand-card rounded-2xl overflow-hidden">
          <div className={`${isWaitlist ? 'bg-[#F59E0B]' : 'bg-[#17120F]'} p-3 flex justify-between items-center`}>
            <span className="text-[10px] font-black text-white tracking-[0.22em] uppercase">{t.entryPass}</span>
            <span className={`text-[9px] font-black px-3 py-1 rounded border-2 uppercase tracking-widest ${isWaitlist ? 'bg-white text-[#17120F] border-[#17120F]' : 'bg-[#FFD51B] text-[#17120F] border-white'}`}>
              {isWaitlist ? t.waitlist : t.confirmed}
            </span>
          </div>
          <div className="p-6 space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[9px] uppercase font-black text-[#8B2D1F] tracking-[0.2em] mb-1">{t.name}</p>
                <h2 className="text-4xl font-black text-[#17120F] uppercase tracking-tight leading-none break-words">{name}</h2>
                <p className="mt-2 text-xs font-black text-[#8B2D1F]">{t.partyOf(partySize)} · {companions}</p>
                {extrasNumbers.length > 0 && (
                  <p className="mt-1 text-[10px] font-black uppercase tracking-widest text-[#8B2D1F]/70">{t.guestNos} {extrasNumbers.map(n => `#${n}`).join(' · ')}</p>
                )}
              </div>
              {attendeeNumber !== null && (
                <div className="shrink-0 rounded-2xl border-2 border-[#17120F] bg-[#FFD51B] px-3 py-2 text-center shadow-[3px_3px_0_#17120F]">
                  <p className="text-[8px] font-black uppercase tracking-widest text-[#8B2D1F] leading-none">{t.entryNo}</p>
                  <p className="font-display text-3xl font-black leading-none text-[#17120F] tabular-nums mt-1">{attendeeNumber}</p>
                </div>
              )}
            </div>

            {!isWaitlist ? (
              <div className="brand-ticket relative rounded-2xl p-4 flex flex-col items-center gap-3">
                <div className="brand-hanko absolute -right-2 -top-2 flex items-center justify-center px-1.5 py-2 text-[12px] rotate-6" aria-hidden="true">乾杯</div>
                <div className="p-3 bg-white rounded-xl border-2 border-[#17120F] shadow-[4px_4px_0_#E51F1F]">
                  <QRCode value={qrValue} size={188} fgColor="#17120F" role="img" aria-label={`Entry QR code for ${name}`} />
                </div>
                <LiveClock />
                <p className="text-[9px] font-black uppercase tracking-[0.22em] text-[#8B2D1F]">{t.showAtCheckin}</p>
              </div>
            ) : (
              <div className="rounded-2xl border-2 border-[#17120F] bg-[#FFD51B] p-4 shadow-[4px_4px_0_#17120F]">
                <p className="font-black uppercase tracking-widest text-[#17120F] text-sm">{t.standbyMode}</p>
                <p className="mt-1 text-xs font-bold text-[#5B3428]">{t.standbyBody}</p>
              </div>
            )}
          </div>
        </div>

        <div className="brand-card rounded-2xl p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[9px] uppercase font-black text-[#8B2D1F] tracking-widest mb-3">{t.venue}</p>
              <p className="font-black text-[#17120F] text-lg leading-tight">{venue}</p>
              {address && <p className="text-xs font-bold text-[#5B3428] mt-1">{address}</p>}
            </div>
            {mapsLink && (
              <a href={mapsLink} target="_blank" rel="noopener noreferrer"
                className="brand-action min-h-[44px] shrink-0 inline-flex items-center gap-1 text-[10px] font-black px-4 py-2 rounded-xl uppercase tracking-wider">
                {t.maps}
              </a>
            )}
          </div>
        </div>

        {drinks.length > 0 && (
          <div className="brand-card rounded-2xl p-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-[9px] uppercase font-black text-[#8B2D1F] tracking-widest">
                {drinks.length > 1 ? t.drinkTickets : t.firstDrinkTicket}
              </p>
              <span className="brand-stamp font-brush rotate-2 rounded-lg px-2 py-0.5 text-[10px] tracking-[0.12em]" aria-hidden="true">乾杯</span>
            </div>
            <div className="space-y-2">
              {drinks.map((d, i) => <DrinkCard key={i} name={d} />)}
            </div>
          </div>
        )}

        <div className="brand-card rounded-2xl p-5">
          <p className="text-[9px] uppercase font-black text-[#8B2D1F] tracking-widest mb-3">{t.readyCheck}</p>
          <div className="grid grid-cols-3 gap-2">
            {checks.map(check => (
              <div key={check.label} className={`rounded-xl border-2 p-3 text-center ${check.done ? 'bg-white border-[#17120F]' : 'bg-[#FFD51B] border-[#17120F]'}`}>
                <p className="text-lg font-black">{check.done ? '✓' : '!'}</p>
                <p className={`text-[9px] font-black uppercase tracking-widest ${check.done ? 'text-[#17120F]' : 'text-[#8B2D1F]'}`}>{check.label}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="brand-card rounded-2xl p-5">
          <p className="text-[9px] uppercase font-black text-[#8B2D1F] tracking-widest mb-3">{t.offkaiDetails}</p>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-lg font-black text-[#17120F]">{maxCapacity || t.tbd}</p>
              <p className="text-[9px] font-black uppercase tracking-widest text-[#8B2D1F]">{t.capacity}</p>
            </div>
            <div>
              <p className="text-lg font-black text-[#17120F]">{rsvpStatus}</p>
              <p className="text-[9px] font-black uppercase tracking-widest text-[#8B2D1F]">{t.rsvp}</p>
            </div>
            <div>
              <p className="text-lg font-black text-[#17120F]">{eventDeadline ? formatArrivalTime(eventDeadline, t) : t.tbd}</p>
              <p className="text-[9px] font-black uppercase tracking-widest text-[#8B2D1F]">{t.deadline}</p>
            </div>
          </div>
        </div>

        <p className="text-center text-[10px] font-black text-[#8B2D1F] uppercase tracking-widest pt-2">
          {t.personalLink}
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
  const [lang, setLang] = useLang()

  useEffect(() => {
    if (!token) {
      const id = setTimeout(() => setView('no_token'), 0)
      return () => clearTimeout(id)
    }

    fetch(`/api/attendee?token=${encodeURIComponent(token)}`)
      .then(async r => ({ ok: r.ok, status: r.status, body: await r.json() }))
      .then(({ ok, status, body }) => {
        if (ok) { setData(body); setView('ready') }
        else if (status === 404) setView('not_found')
        else if (status >= 500) setView('unavailable')
        else setView('invalid')
      })
      .catch(() => setView('unavailable'))
  }, [token])

  const t = STRINGS[lang]

  let content: React.ReactNode = null
  if (view === 'loading') content = (
    <div className="brand-rays min-h-dvh flex items-center justify-center">
      <div className="brand-seal px-5 py-3 text-sm font-black uppercase tracking-widest text-white animate-pulse">{t.loading}</div>
    </div>
  )
  else if (view === 'no_token') content = <NoToken />
  else if (view === 'invalid') content = <InvalidToken reason="invalid" />
  else if (view === 'not_found') content = <InvalidToken reason="not_found" />
  else if (view === 'unavailable') content = <InvalidToken reason="unavailable" />
  else if (view === 'ready' && data) content = <RSVPCard data={data} token={token!} />

  return (
    <LangContext.Provider value={{ lang, t, setLang }}>
      {content}
    </LangContext.Provider>
  )
}

export default function Page() {
  return (
    <Suspense fallback={
      <div className="brand-rays min-h-dvh flex items-center justify-center">
        <div className="brand-seal px-5 py-3 text-sm font-black uppercase tracking-widest text-white">Loading...</div>
      </div>
    }>
      <AttendeeView />
    </Suspense>
  )
}
