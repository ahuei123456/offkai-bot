'use client'
import { useEffect, useState } from 'react'
import type { AttendeeData, ViewState } from '../lib/types'

// Resolves an attendee pass from its token: loading -> ready / no_token /
// invalid / not_found / unavailable.
export function usePass(token: string | null) {
  const [view, setView] = useState<ViewState>('loading')
  const [data, setData] = useState<AttendeeData | null>(null)

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

  return { view, data }
}
