'use client'
import { useState } from 'react'
import { useT } from '../../lib/i18n'
import type { Attendee } from '../../lib/types'

export function RemoveRegistration({ attendee, onRemove }: {
  attendee: Attendee; onRemove: (userId: string) => Promise<boolean>
}) {
  const { t } = useT()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  async function remove() {
    if (!window.confirm(t.confirmRemove(attendee.display_name || attendee.username))) return
    setBusy(true)
    setError(false)
    try { setError(!await onRemove(attendee.user_id)) } catch { setError(true) }
    finally { setBusy(false) }
  }
  return <div className="border-t-2 border-[#17120F] p-3 text-xs">
    <div className="flex justify-end">
      <button type="button" className="brand-action min-h-[44px] rounded-xl px-3 py-2 font-black"
        disabled={busy} onClick={remove}>{busy ? t.loading : t.removeUser}</button>
    </div>
    {error && <p role="alert" className="mt-2 text-red-700">{t.removalError}</p>}
  </div>
}
