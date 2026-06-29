import type { ScanResultKind } from './types'

// How long the scan popup stays up before auto-dismissing and resuming scanning.
export const POPUP_MS: Record<ScanResultKind, number> = {
  checked_in: 3500, already_checked_in: 3500, wrong_event: 4500, invalid_qr: 4500, error: 6000,
}

export const SCAN_RESULT_META: Record<ScanResultKind, { ok: boolean; badge: string; title: string }> = {
  checked_in:         { ok: true,  badge: 'OK',    title: 'Checked In!' },
  already_checked_in: { ok: true,  badge: 'Again', title: 'Already Checked In' },
  wrong_event:        { ok: false, badge: 'Stop',  title: 'Wrong Event' },
  invalid_qr:         { ok: false, badge: 'NG',    title: 'Invalid QR' },
  error:              { ok: false, badge: 'NG',    title: 'Camera Error' },
}
