import assert from 'node:assert/strict'
import test from 'node:test'
// Node's native TypeScript runner requires the explicit extension, while the
// application tsconfig intentionally disallows it for production imports.
// @ts-expect-error TS5097: this specifier is only used by the Node test runner.
import { getDefaultEvent, isSelectableForCheckin } from './db.ts'

// The frontend previously had no test runner. Node can execute this small API
// regression suite directly while stripping TypeScript syntax, without adding
// a test framework just for route coverage. The API routes use this helper for
// their default and direct event-selection guards.

const interestEvent = {
  event_name: 'Possible Karaoke Night',
  venue: null,
  address: null,
  google_maps_link: null,
  event_datetime: null,
  event_deadline: null,
  open: true,
  archived: false,
  drinks: [],
  max_capacity: null,
  interest_check: true,
}

test('interest checks never become the default check-in event', () => {
  assert.equal(getDefaultEvent([interestEvent]), null)
})

test('interest checks are never selectable for direct check-in or attendee-token API requests', () => {
  assert.equal(isSelectableForCheckin(interestEvent), false)
  assert.equal(isSelectableForCheckin({ ...interestEvent, interest_check: false }), true)
})
