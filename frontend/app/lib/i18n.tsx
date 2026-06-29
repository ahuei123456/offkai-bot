'use client'
import { createContext, useCallback, useContext, useSyncExternalStore } from 'react'

export type Lang = 'en' | 'ja'

export const STRINGS = {
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

export type Strings = typeof STRINGS['en']

const LangContext = createContext<{ lang: Lang; t: Strings; setLang: (l: Lang) => void }>({
  lang: 'en', t: STRINGS.en, setLang: () => {},
})

export const useT = () => useContext(LangContext)

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

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useLang()
  return (
    <LangContext.Provider value={{ lang, t: STRINGS[lang], setLang }}>
      {children}
    </LangContext.Provider>
  )
}

export function LangToggle({ className = '' }: { className?: string }) {
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
