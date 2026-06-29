'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import type { Attendee, CheckinRecord, ScanResult } from '../lib/types'
import { POPUP_MS } from '../lib/scan'

const SCANNER_DIV_ID = 'qr-scanner-container'

type ScannerArgs = {
  adminKey: string
  selectedEvent: string
  attendees: Attendee[]
  onCheckedIn: (record: CheckinRecord) => void
}

// Owns the html5-qrcode camera scanner and the confirmation-popup lifecycle.
// Reads the live admin key / event / attendees through refs so the long-lived
// decode callback never goes stale.
export function useScanner({ adminKey, selectedEvent, attendees, onCheckedIn }: ScannerArgs) {
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [popupMsLeft, setPopupMsLeft] = useState(0)

  const scannerRef = useRef<{ stop: () => Promise<void>; clear?: () => void } | null>(null)
  const Html5QrcodeRef = useRef<typeof import('html5-qrcode').Html5Qrcode | null>(null)
  const keyRef = useRef('')
  const selectedEventRef = useRef('')
  const attendeesRef = useRef<Attendee[]>([])
  const onCheckedInRef = useRef(onCheckedIn)

  // Keep refs in sync so the scan callback always reads current values.
  useEffect(() => { keyRef.current = adminKey }, [adminKey])
  useEffect(() => { selectedEventRef.current = selectedEvent }, [selectedEvent])
  useEffect(() => { attendeesRef.current = attendees }, [attendees])
  useEffect(() => { onCheckedInRef.current = onCheckedIn }, [onCheckedIn])

  // Pre-load the QR library on mount. Importing it inside the click handler is a
  // network fetch that crosses a task boundary and revokes the browser's
  // user-gesture context, which makes getUserMedia throw NotAllowedError on
  // iOS/Android even after the user grants the camera permission.
  useEffect(() => {
    let cancelled = false
    import('html5-qrcode').then(({ Html5Qrcode }) => {
      if (!cancelled) Html5QrcodeRef.current = Html5Qrcode
    }).catch(() => { /* surfaced on first scan attempt */ })
    return () => { cancelled = true }
  }, [])

  // Show a scan result and seed its countdown here (event-handler context) so
  // the lifecycle effect only has to tick the timer down, never seed it.
  const presentScan = useCallback((r: ScanResult) => {
    setScanResult(r)
    setPopupMsLeft(r.fromScan && r.kind !== 'error' ? POPUP_MS[r.kind] : 0)
  }, [])

  const stopScanner = useCallback(async () => {
    if (scannerRef.current) {
      try { await scannerRef.current.stop() } catch { /* ignore */ }
      try { scannerRef.current.clear?.() } catch { /* ignore */ }
      scannerRef.current = null
    }
    setScanning(false)
  }, [])

  const startScanner = useCallback(async () => {
    const QrScanner = Html5QrcodeRef.current
    if (!QrScanner) {
      presentScan({ kind: 'error', name: 'Scanner not ready — reload the page and try again', fromScan: false })
      return
    }

    // flushSync so the target div is in the DOM with real dimensions before
    // html5-qrcode measures it.
    flushSync(() => {
      setScanResult(null)
      setScanning(true)
    })

    const scanner = new QrScanner(SCANNER_DIV_ID)
    scannerRef.current = scanner

    try {
      await scanner.start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 250, height: 250 } },
        async (decodedText: string) => {
          await stopScanner()

          // Extract the token. Only accept QR codes whose URL is the SAME ORIGIN
          // as this admin page, so a malicious QR can't smuggle in a foreign
          // link — and we never navigate to the decoded value, only read its
          // token. Assumes attendees + admin are served from one public domain
          // (e.g. https://offkai.example.com/?token=... and /admin). It would
          // reject valid QRs if staff opened admin on a different origin such as
          // a LAN IP (http://192.168.x.x:8090/admin); loosen here if that's ever
          // needed.
          let token: string | null = null
          try {
            const url = new URL(decodedText)
            if (url.origin !== window.location.origin) {
              presentScan({ kind: 'invalid_qr', name: 'This code is not from this site', fromScan: true })
              return
            }
            token = url.searchParams.get('token')
          } catch {
            // Not a URL — treat the raw text as the token.
            token = decodedText
          }

          if (!token) {
            presentScan({ kind: 'invalid_qr', name: 'No check-in token found', fromScan: true })
            return
          }

          const ev = selectedEventRef.current
          const evParam = ev ? `&event=${encodeURIComponent(ev)}` : ''
          const res = await fetch(`/api/checkin?key=${encodeURIComponent(keyRef.current)}${evParam}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, event_name: ev || undefined }),
          })
          const data = await res.json().catch(() => ({}))

          if (res.ok && data.record) {
            const att = attendeesRef.current.find(a => a.user_id === data.record.user_id)
            presentScan({
              kind: data.already_checked_in ? 'already_checked_in' : 'checked_in',
              name: data.record.name || 'Guest',
              fromScan: true,
              extraPeople: att?.extra_people ?? 0,
              extrasNames: att?.extras_names ?? [],
              attendeeNumber: att?.attendee_number ?? null,
              extrasNumbers: att?.extras_attendee_numbers ?? [],
              time: new Date(data.record.checked_in_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
            })
            onCheckedInRef.current(data.record)
          } else if (data.error === 'wrong_event') {
            presentScan({ kind: 'wrong_event', name: `QR is for "${data.token_event}", not the selected event`, fromScan: true })
          } else if (data.error === 'attendee_not_in_event') {
            presentScan({ kind: 'wrong_event', name: 'Not registered for this event', fromScan: true })
          } else {
            presentScan({ kind: 'invalid_qr', name: 'QR code not recognised', fromScan: true })
          }
        },
        () => { /* per-frame decode misses — ignore */ }
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const lower = msg.toLowerCase()
      const isPermission = lower.includes('notallowed') || lower.includes('permission') || lower.includes('denied')
      const noCamera = lower.includes('notfound') || lower.includes('no camera') || lower.includes('overconstrained')
      setScanning(false)
      scannerRef.current = null
      presentScan({
        kind: 'error',
        fromScan: false,
        name: isPermission
          ? 'Camera blocked. Allow camera access in your browser settings, then reload.'
          : noCamera
            ? 'No camera found on this device.'
            : msg,
      })
    }
  }, [stopScanner, presentScan])

  // Scan popup lifecycle: a live decode shows a full-screen confirmation with a
  // millisecond countdown, then auto-dismisses and resumes scanning so staff can
  // keep waving QRs through. Setup/camera errors (fromScan=false) wait for a tap.
  useEffect(() => {
    if (!scanResult || !scanResult.fromScan) return
    const total = POPUP_MS[scanResult.kind]
    const start = Date.now()
    const id = setInterval(() => {
      const left = total - (Date.now() - start)
      if (left <= 0) {
        clearInterval(id)
        setPopupMsLeft(0)
        setScanResult(null)
        if (scanResult.kind !== 'error') startScanner()
      } else {
        setPopupMsLeft(left)
      }
    }, 47)
    return () => clearInterval(id)
  }, [scanResult, startScanner])

  const dismissPopup = useCallback(() => {
    const wasScan = scanResult?.fromScan && scanResult.kind !== 'error'
    setScanResult(null)
    if (wasScan) startScanner()
  }, [scanResult, startScanner])

  const clearResult = useCallback(() => setScanResult(null), [])

  return {
    scannerDivId: SCANNER_DIV_ID,
    scanning, scanResult, popupMsLeft,
    startScanner, stopScanner, dismissPopup, clearResult,
  }
}
