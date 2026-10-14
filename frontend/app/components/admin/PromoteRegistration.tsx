'use client'
import { useRef, useState } from 'react'
import { useT } from '../../lib/i18n'
import type { Attendee } from '../../lib/types'

export function PromoteRegistration({ attendee, onPromote }: {
  attendee: Attendee; onPromote: (userId: string, timestamp: string) => Promise<boolean>
}) {
  const { t } = useT()
  const inFlight = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<'unconfirmed' | 'not_promoted' | 'registration_changed' | null>(null)
  async function promote() {
    if (inFlight.current || attendee.status !== 'waitlist') return
    const timestamp = attendee.registration_timestamp
    if (!timestamp || !Number.isFinite(Date.parse(timestamp))) { setError('not_promoted'); return }
    if (!window.confirm(t.confirmPromote(attendee.display_name || attendee.username))) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try { if (!await onPromote(attendee.user_id, timestamp)) setError('unconfirmed') }
    catch (failure) {
      const message = failure instanceof Error ? failure.message : ''
      setError(message === 'registration_changed' || message === 'not_promoted' ? message : 'unconfirmed')
    }
    finally { inFlight.current = false; setBusy(false) }
  }
  return <div className="text-xs">
    <button type="button" className="w-11 h-11 rounded-xl border-2 border-[#17120F] bg-green-50 text-green-800 flex items-center justify-center shrink-0 active:translate-x-[1px] active:translate-y-[1px] transition"
      disabled={busy || !attendee.registration_timestamp || attendee.status !== 'waitlist'} onClick={promote}
      aria-label={t.promoteUser} title={t.promoteUser}>
      {busy ? '…' : <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 19V5M5 12l7-7 7 7" />
      </svg>}
    </button>
    {error && <p role="alert" className="mt-2 text-red-700">{error === 'registration_changed' ? t.promotionRegistrationChanged : error === 'not_promoted' ? t.promotionNotStarted : t.promotionError}</p>}
  </div>
}
