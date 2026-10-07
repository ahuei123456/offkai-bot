import { getDefaultEvent, isSelectableForCheckin, readEvents, readResponses } from './db'
import type { ResolvedToken } from './token'
import type { Event } from './db'

export function paymentEnabled(event: Event) {
  return !!event.signup_form?.payment_methods && Object.keys(event.signup_form.payment_methods).length > 0
}

export function paymentRegistration(eventName: string, userId: string) {
  const event = readEvents().find(e => e.event_name === eventName && isSelectableForCheckin(e))
  if (!event || !paymentEnabled(event)) return null
  const responses = readResponses()[eventName]
  const attendee = [...(responses?.attendees || []), ...(responses?.waitlist || [])].find(a => a.user_id === userId)
  return attendee ? { event, attendee } : null
}
export function tokenPaymentRegistration(resolved: ResolvedToken) {
  const name = resolved.eventName || getDefaultEvent(readEvents())?.event_name
  return name ? paymentRegistration(name, resolved.userId) : null
}
