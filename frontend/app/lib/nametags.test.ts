import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import type { Attendee } from './types.ts'
import {
  buildNametagEntries,
  calculateSheetLayout,
  DEFAULT_NAMETAG_SHEET,
  normalizeSheetSettings,
} from './nametags.ts'

const attendees: Attendee[] = [
  {
    user_id: '300',
    username: 'tomori',
    display_name: 'Tomori Takamatsu',
    drinks: ['Cream Soda (L)'],
    extra_people: 2,
    extras_names: ['Anon Chihaya', 'Raana'],
    attendee_number: 7,
    extras_attendee_numbers: [8, 9],
    status: 'attending',
  },
  {
    user_id: '301',
    username: 'soyo',
    display_name: null,
    drinks: ['Oolong Tea (L)'],
    extra_people: 0,
    extras_names: [],
    attendee_number: 10,
    extras_attendee_numbers: [],
    status: 'attending',
  },
  {
    user_id: '999',
    username: 'waitchan',
    display_name: 'Wait Chan',
    drinks: [],
    extra_people: 0,
    extras_names: [],
    attendee_number: null,
    extras_attendee_numbers: [],
    status: 'waitlist',
  },
]

describe('buildNametagEntries', () => {
  it('creates one printable sticker for each attending person and guest, excluding waitlist by default', () => {
    const entries = buildNametagEntries(attendees)

    assert.equal(entries.length, 4)
    assert.deepEqual(entries.map(e => e.name), ['Tomori Takamatsu', 'Anon Chihaya', 'Raana', 'soyo'])
    assert.deepEqual(entries.map(e => e.number), [7, 8, 9, 10])
    assert.equal(entries[0].discordLine, '@tomori')
    assert.equal('drinkLine' in entries[0], false)
    assert.equal(entries[1].discordLine, 'Guest of @tomori')
    assert.equal('drinkLine' in entries[1], false)
    assert.equal(entries[1].kind, 'guest')
  })

  it('can include waitlist entries as standby stickers when requested', () => {
    const entries = buildNametagEntries(attendees, { includeWaitlist: true })

    assert.equal(entries.at(-1)?.status, 'waitlist')
    assert.equal(entries.at(-1)?.numberLabel, 'WAIT')
  })
})

describe('calculateSheetLayout', () => {
  it('calculates arbitrary sticker sheet capacity from paper, margins, sticker box, and gutters', () => {
    const layout = calculateSheetLayout({
      paperWidthMm: 210,
      paperHeightMm: 297,
      marginTopMm: 12,
      marginRightMm: 8,
      marginBottomMm: 12,
      marginLeftMm: 8,
      stickerWidthMm: 63,
      stickerHeightMm: 38.1,
      gutterXMm: 2.5,
      gutterYMm: 2.5,
    })

    assert.equal(layout.columns, 3)
    assert.equal(layout.rows, 6)
    assert.equal(layout.perPage, 18)
    assert.equal(layout.contentWidthMm, 194)
  })

  it('keeps the default sheet compact instead of using most of the page for oversized cards', () => {
    const layout = calculateSheetLayout(DEFAULT_NAMETAG_SHEET)

    assert.equal(DEFAULT_NAMETAG_SHEET.stickerWidthMm, 60)
    assert.equal(DEFAULT_NAMETAG_SHEET.stickerHeightMm, 32)
    assert.equal(layout.columns, 3)
    assert.equal(layout.rows, 8)
    assert.equal(layout.perPage, 24)
  })

  it('normalizes unsafe values to printable defaults instead of generating impossible CSS', () => {
    const normalized = normalizeSheetSettings({ ...DEFAULT_NAMETAG_SHEET, paperWidthMm: -1, stickerWidthMm: 999 })
    const layout = calculateSheetLayout(normalized)

    assert.equal(normalized.paperWidthMm, DEFAULT_NAMETAG_SHEET.paperWidthMm)
    assert.equal(normalized.stickerWidthMm, DEFAULT_NAMETAG_SHEET.stickerWidthMm)
    assert.ok(layout.columns >= 1)
    assert.ok(layout.rows >= 1)
  })
})
