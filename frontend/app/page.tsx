'use client'
import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { LangProvider, useT } from './lib/i18n'
import { usePass } from './hooks/usePass'
import { LoadingScreen, NoToken, InvalidToken } from './components/pass/StateScreens'
import { RSVPCard } from './components/pass/RSVPCard'

function AttendeeView() {
  const token = useSearchParams().get('token')
  const { view, data } = usePass(token)
  const { t } = useT()

  if (view === 'loading') return <LoadingScreen label={t.loading} />
  if (view === 'no_token') return <NoToken />
  if (view === 'invalid') return <InvalidToken reason="invalid" />
  if (view === 'not_found') return <InvalidToken reason="not_found" />
  if (view === 'unavailable') return <InvalidToken reason="unavailable" />
  if (view === 'ready' && data) return <RSVPCard data={data} token={token!} />
  return null
}

export default function Page() {
  return (
    <Suspense fallback={<LoadingScreen />}>
      <LangProvider>
        <AttendeeView />
      </LangProvider>
    </Suspense>
  )
}
