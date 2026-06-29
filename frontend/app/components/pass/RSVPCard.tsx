'use client'
import QRCode from 'react-qr-code'
import { useT, LangToggle } from '../../lib/i18n'
import { formatArrivalTime, getEventPhase } from '../../lib/format'
import type { AttendeeData } from '../../lib/types'
import { BrandSign } from '../BrandSign'
import { LiveClock } from '../LiveClock'
import { LanternGarland, KaraageBoat } from '../izakaya-art'
import { DrinkCard } from './DrinkCard'

export function RSVPCard({ data, token }: { data: AttendeeData; token: string }) {
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
          <BrandSign variant="pass" subtitle={t.rsvpPass} />
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
                <LiveClock label={t.live} className="flex shadow-[3px_3px_0_#E51F1F]" />
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
