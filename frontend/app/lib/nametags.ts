import type { Attendee } from './types'

export type StickerTheme = 'chibachan' | 'classic-red' | 'ink'

export type NametagSheetSettings = {
  paperWidthMm: number
  paperHeightMm: number
  marginTopMm: number
  marginRightMm: number
  marginBottomMm: number
  marginLeftMm: number
  stickerWidthMm: number
  stickerHeightMm: number
  gutterXMm: number
  gutterYMm: number
  includeWaitlist: boolean
  theme: StickerTheme
}

export type NametagEntry = {
  id: string
  name: string
  number: number | null
  numberLabel: string
  discordLine: string
  subLine: string
  status: Attendee['status']
  kind: 'attendee' | 'guest'
}

export type SheetLayout = {
  contentWidthMm: number
  contentHeightMm: number
  columns: number
  rows: number
  perPage: number
}

export const DEFAULT_NAMETAG_SHEET: NametagSheetSettings = {
  paperWidthMm: 210,
  paperHeightMm: 297,
  marginTopMm: 8,
  marginRightMm: 7,
  marginBottomMm: 8,
  marginLeftMm: 7,
  stickerWidthMm: 63.5,
  stickerHeightMm: 56.2,
  gutterXMm: 2,
  gutterYMm: 0,
  includeWaitlist: false,
  theme: 'chibachan',
}

const DEFAULT_BOUNDS = {
  paperWidthMm: [25, 1000],
  paperHeightMm: [25, 1000],
  marginTopMm: [0, 200],
  marginRightMm: [0, 200],
  marginBottomMm: [0, 200],
  marginLeftMm: [0, 200],
  stickerWidthMm: [10, 500],
  stickerHeightMm: [10, 500],
  gutterXMm: [0, 100],
  gutterYMm: [0, 100],
} as const

type NumberSetting = keyof typeof DEFAULT_BOUNDS

function safeNumber(value: number, fallback: number, min: number, max: number) {
  if (!Number.isFinite(value) || value < min || value > max) return fallback
  return Math.round(value * 100) / 100
}

export function normalizeSheetSettings(settings: NametagSheetSettings): NametagSheetSettings {
  const normalized = { ...settings }
  for (const key of Object.keys(DEFAULT_BOUNDS) as NumberSetting[]) {
    const [min, max] = DEFAULT_BOUNDS[key]
    normalized[key] = safeNumber(settings[key], DEFAULT_NAMETAG_SHEET[key], min, max)
  }

  const usableWidth = normalized.paperWidthMm - normalized.marginLeftMm - normalized.marginRightMm
  if (usableWidth < normalized.stickerWidthMm) {
    normalized.marginLeftMm = DEFAULT_NAMETAG_SHEET.marginLeftMm
    normalized.marginRightMm = DEFAULT_NAMETAG_SHEET.marginRightMm
    normalized.stickerWidthMm = DEFAULT_NAMETAG_SHEET.stickerWidthMm
  }

  const usableHeight = normalized.paperHeightMm - normalized.marginTopMm - normalized.marginBottomMm
  if (usableHeight < normalized.stickerHeightMm) {
    normalized.marginTopMm = DEFAULT_NAMETAG_SHEET.marginTopMm
    normalized.marginBottomMm = DEFAULT_NAMETAG_SHEET.marginBottomMm
    normalized.stickerHeightMm = DEFAULT_NAMETAG_SHEET.stickerHeightMm
  }

  return normalized
}

export function calculateSheetLayout(settings: NametagSheetSettings): SheetLayout {
  const safe = normalizeSheetSettings(settings)
  const contentWidthMm = Math.max(0, safe.paperWidthMm - safe.marginLeftMm - safe.marginRightMm)
  const contentHeightMm = Math.max(0, safe.paperHeightMm - safe.marginTopMm - safe.marginBottomMm)
  const columns = Math.max(1, Math.floor((contentWidthMm + safe.gutterXMm) / (safe.stickerWidthMm + safe.gutterXMm)))
  const rows = Math.max(1, Math.floor((contentHeightMm + safe.gutterYMm) / (safe.stickerHeightMm + safe.gutterYMm)))

  return { contentWidthMm, contentHeightMm, columns, rows, perPage: columns * rows }
}

export function buildNametagEntries(attendees: Attendee[], options: { includeWaitlist?: boolean } = {}): NametagEntry[] {
  const entries: NametagEntry[] = []
  const included = attendees.filter(a => a.status === 'attending' || options.includeWaitlist)

  for (const attendee of included) {
    const primaryName = attendee.display_name || attendee.username
    entries.push({
      id: `${attendee.user_id}:primary`,
      name: primaryName,
      number: attendee.attendee_number,
      numberLabel: attendee.attendee_number == null ? (attendee.status === 'waitlist' ? 'WAIT' : '—') : String(attendee.attendee_number),
      discordLine: `@${attendee.username} · ${attendee.user_id}`,
      subLine: attendee.status === 'waitlist' ? 'STANDBY / WAITLIST' : 'CONFIRMED OFFKAI PASS',
      status: attendee.status,
      kind: 'attendee',
    })

    if (attendee.status !== 'attending') continue

    for (let index = 0; index < (attendee.extra_people ?? 0); index += 1) {
      const guestName = attendee.extras_names[index] || `Guest ${index + 1}`
      const guestNumber = attendee.extras_attendee_numbers[index] ?? null
      entries.push({
        id: `${attendee.user_id}:guest:${index}`,
        name: guestName,
        number: guestNumber,
        numberLabel: guestNumber == null ? 'GUEST' : String(guestNumber),
        discordLine: `Guest of @${attendee.username}`,
        subLine: primaryName,
        status: 'attending',
        kind: 'guest',
      })
    }
  }

  return entries
}

export function chunkNametagEntries(entries: NametagEntry[], perPage: number): NametagEntry[][] {
  const safePerPage = Math.max(1, perPage)
  const pages: NametagEntry[][] = []
  for (let index = 0; index < entries.length; index += safePerPage) {
    pages.push(entries.slice(index, index + safePerPage))
  }
  return pages.length ? pages : [[]]
}
