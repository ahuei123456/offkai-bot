'use client'
import { useCallback, useState } from 'react'
import { useAdminData } from '../hooks/useAdminData'
import { useScanner } from '../hooks/useScanner'
import { AdminLogin } from '../components/admin/AdminLogin'
import { StatHeader } from '../components/admin/StatHeader'
import { FilterBar } from '../components/admin/FilterBar'
import { AttendeeRow } from '../components/admin/AttendeeRow'
import { WaitlistList } from '../components/admin/WaitlistList'
import { ScanPopup } from '../components/admin/ScanPopup'
import { NametagSheetGenerator } from '../components/admin/NametagSheetGenerator'

export default function AdminPage() {
  const data = useAdminData()
  const [nametagDialogOpen, setNametagDialogOpen] = useState(false)
  const scanner = useScanner({
    adminKey: data.key,
    selectedEvent: data.selectedEvent,
    attendees: data.attendees,
    onCheckedIn: data.applyScanCheckin,
  })

  // Switching events clears both the sticky rows (data) and any open scan popup.
  const changeEvent = useCallback((next: string) => {
    data.changeEvent(next)
    scanner.clearResult()
  }, [data, scanner])

  if (!data.authed) {
    return (
      <AdminLogin
        keyInput={data.keyInput}
        setKeyInput={data.setKeyInput}
        loginError={data.loginError}
        onLogin={data.handleLogin}
      />
    )
  }

  return (
    <main className="brand-bg min-h-dvh w-full max-w-6xl mx-auto text-[#23110D] pb-12">
      <StatHeader
        eventName={data.eventName}
        events={data.events}
        selectedEvent={data.selectedEvent}
        onChangeEvent={changeEvent}
        pendingCount={data.pendingCount}
        checkedInCount={data.checkedInCount}
        attendingCount={data.attendingCount}
        waitlistCount={data.waitlistCount}
        scanning={scanner.scanning}
        onToggleScan={scanner.scanning ? scanner.stopScanner : scanner.startScanner}
        onOpenNametags={() => setNametagDialogOpen(true)}
      />

      <FilterBar
        filter={data.filter}
        onChangeFilter={data.changeFilter}
        search={data.search}
        onSearch={data.setSearch}
      />

      <div className="p-4 space-y-4 lg:p-6">
        {/* Scanner — div is always mounted so html5-qrcode can attach to it. */}
        <div className={`brand-card rounded-2xl overflow-hidden ${scanner.scanning ? '' : 'hidden'}`}>
          <div id={scanner.scannerDivId} className="w-full" />
        </div>

        <div className="space-y-2">
          {data.filtered.map(a => (
            <AttendeeRow
              key={a.user_id}
              attendee={a}
              checkin={data.checkins[a.user_id]}
              onCheckin={data.manualCheckin}
              onCheckout={data.manualCheckout}
            />
          ))}
          {data.filtered.length === 0 && (
            <p className="text-center text-sm font-black text-[#8B2D1F] py-8">No attendees found</p>
          )}
        </div>

        {data.filter === 'all' && !data.search && <WaitlistList waitlist={data.waitlist} />}
      </div>

      {scanner.scanResult && (
        <ScanPopup result={scanner.scanResult} popupMsLeft={scanner.popupMsLeft} onDismiss={scanner.dismissPopup} />
      )}

      {nametagDialogOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-[#17120F]/70 p-3 backdrop-blur-sm md:p-6" role="dialog" aria-modal="true" aria-label="Nametag printer">
          <div className="mx-auto flex max-w-6xl flex-col gap-3">
            <div className="nametag-print-controls flex justify-end">
              <button
                type="button"
                onClick={() => setNametagDialogOpen(false)}
                className="min-h-[44px] rounded-xl border-2 border-[#17120F] bg-white px-4 py-2 text-xs font-black uppercase tracking-widest text-[#17120F] shadow-[3px_3px_0_#FFD51B]"
              >
                Close
              </button>
            </div>
            <NametagSheetGenerator attendees={data.attendees} eventName={data.eventName} />
          </div>
        </div>
      )}
    </main>
  )
}
