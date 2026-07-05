import type { Attendee } from './types'

export type StickerTheme = 'plain' | 'chibachan' | 'classic-red' | 'ink'

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
  paperWidthMm: 215.9,
  paperHeightMm: 279.4,
  marginTopMm: 12.7,
  marginRightMm: 14.2,
  marginBottomMm: 12.7,
  marginLeftMm: 14.2,
  stickerWidthMm: 85.73,
  stickerHeightMm: 59.27,
  gutterXMm: 15.7,
  gutterYMm: 5.64,
  includeWaitlist: false,
  theme: 'plain',
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
      discordLine: `@${attendee.username}`,
      subLine: attendee.status === 'waitlist' ? 'WAITLIST' : '',
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
        subLine: `Guest of ${primaryName}`,
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
