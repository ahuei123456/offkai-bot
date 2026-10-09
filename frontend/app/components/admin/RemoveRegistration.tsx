'use client'
import { useState } from 'react'
import { useT } from '../../lib/i18n'
import type { Attendee } from '../../lib/types'

export function RemoveRegistration({ attendee, onRemove }: {
  attendee: Attendee; onRemove: (userId: string, timestamp: string) => Promise<boolean>
}) {
  const { t } = useT()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<'unconfirmed' | 'not_removed' | 'registration_changed' | null>(null)
  async function remove() {
    const timestamp = attendee.registration_timestamp
    if (!timestamp || !Number.isFinite(Date.parse(timestamp))) { setError('not_removed'); return }
    if (!window.confirm(t.confirmRemove(attendee.display_name || attendee.username))) return
    setBusy(true)
    setError(null)
    try { if (!await onRemove(attendee.user_id, timestamp)) setError('unconfirmed') }
    catch (failure) {
      const message = failure instanceof Error ? failure.message : ''
      setError(message === 'registration_changed' || message === 'not_removed' ? message : 'unconfirmed')
    }
    finally { setBusy(false) }
  }
  return <div className="text-xs">
    <button type="button" className="w-11 h-11 rounded-xl border-2 border-[#17120F] bg-red-50 text-red-700 flex items-center justify-center shrink-0 active:translate-x-[1px] active:translate-y-[1px] transition"
      disabled={busy} onClick={remove} aria-label={t.removeUser} title={t.removeUser}>
      {busy ? '…' : <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6" />
      </svg>}
    </button>
    {error && <p role="alert" className="mt-2 text-red-700">{error === 'registration_changed' ? t.removalRegistrationChanged : error === 'not_removed' ? t.removalNotStarted : t.removalError}</p>}
  </div>
}
