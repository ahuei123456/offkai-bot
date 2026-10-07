import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import type { ReactElement, ReactNode } from 'react'

test('same-event token change replaces the payment card rather than retaining another registration state', async () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.payment-token-test-'))
  try {
    fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
    fs.writeFileSync(path.join(dir, 'view-stubs.js'), `
      export default function QRCode() { return null; }
      export function useT() { return { t: { partyOf: n => String(n), guests: n => String(n) } }; }
      export function PaymentCard() { return null; }
      export function LangToggle() { return null; }
      export function BrandSign() { return null; }
      export function LiveClock() { return null; }
      export function LanternGarland() { return null; }
      export function KaraageBoat() { return null; }
      export function DrinkCard() { return null; }
      export function buildGoogleMapsDirectionsUrl() { return ''; }
      export function buildGoogleMapsEmbedUrl() { return ''; }
      export function formatArrivalTime() { return ''; }
      export function getEventPhase() { return ''; }
    `)
    // Render the actual parent JSX and inspect the child's React reconciliation
    // identity. Auxiliary visual components are irrelevant to token isolation.
    const source = fs.readFileSync(path.join(process.cwd(), 'app/components/pass/RSVPCard.tsx'), 'utf8')
    const code = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText.replace(/from ['"](?:\.[^'"]+|react-qr-code)['"]/g, "from './view-stubs.js'")
    fs.writeFileSync(path.join(dir, 'card.js'), code)
    const { RSVPCard } = await import(pathToFileURL(path.join(dir, 'card.js')).href)
    const { PaymentCard } = await import(pathToFileURL(path.join(dir, 'view-stubs.js')).href)
    function findPayment(node: ReactNode): ReactElement<{ payment: { paid: boolean; proof: unknown }; token: string }> | undefined {
      if (Array.isArray(node)) {
        for (const child of node) { const found = findPayment(child); if (found) return found }
      } else if (node && typeof node === 'object' && 'type' in node && 'props' in node) {
        const element = node as ReactElement<{ children?: ReactNode }>
        if (element.type === PaymentCard) return element as ReturnType<typeof findPayment>
        return findPayment(element.props.children)
      }
    }
    const paid = { paid: true, proof: { filename: 'synthetic.webp' } }
    const unpaid = { paid: false, proof: null }
    const render = (token: string, payment: typeof paid | typeof unpaid, eventName = 'Same event') => findPayment(RSVPCard({
      token, data: { event: { event_name: eventName }, attendee: { status: 'attending', payment, payment_enabled: true } },
    }))!
    const first = render('signed-user-A', paid)
    const switched = render('signed-user-B', unpaid)
    assert.notEqual(switched.key, first.key)
    assert.deepEqual(switched.props.payment, unpaid)
    assert.equal(switched.props.token, 'signed-user-B')
    assert.equal(render('signed-user-B', unpaid).key, switched.key)
    assert.notEqual(render('signed-user-B', unpaid, 'Another event').key, switched.key)
    assert.equal(findPayment(RSVPCard({ token: 'no-payment', data: {
      event: { event_name: 'No prepayment' }, attendee: { status: 'attending', payment_enabled: false },
    } })), undefined)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('page resets pass state before a delayed same-event token response arrives', async () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.pass-token-test-'))
  const previousFetch = globalThis.fetch
  try {
    fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
    fs.writeFileSync(path.join(dir, 'stubs.js'), `
      export function Suspense() {} export function LangProvider() {}
      export function LoadingScreen() {} export function NoToken() {}
      export function InvalidToken() {} export function RSVPCard() {}
      export function useT() { return { t: { loading: 'Loading' } }; }
      let token; export function select(value) { token = value; }
      export function useSearchParams() { return { get: () => token }; }
    `)
    fs.writeFileSync(path.join(dir, 'react.js'), `
      const instances = new Map(); let current; let index; let effects;
      export function begin(key) { current = instances.get(key);
        if (!current) { current = []; instances.set(key, current); }
        index = 0; effects = []; }
      export function useState(initial) { const state = current; const i = index++;
        if (!(i in state)) state[i] = initial;
        return [state[i], value => { state[i] = value; }]; }
      export function useEffect(fn, deps) { const i = index++;
        if (current[i] !== deps[0]) { current[i] = deps[0]; effects.push(fn); } }
      export function runEffects() { for (const fn of effects) fn(); }
    `)
    const compile = (file: string) => ts.transpileModule(fs.readFileSync(path.join(process.cwd(), file), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    fs.writeFileSync(path.join(dir, 'hook.js'), compile('app/hooks/usePass.ts').replace("from 'react'", "from './react.js'"))
    fs.writeFileSync(path.join(dir, 'page.js'), compile('app/page.tsx')
      .replace(/from ['"]\.\/hooks\/usePass['"]/g, "from './hook.js'")
      .replace(/from ['"](?:react|next\/navigation|\.\/lib\/i18n|\.\/components\/pass\/[^'"]+)['"]/g, "from './stubs.js'"))
    const { default: Page } = await import(pathToFileURL(path.join(dir, 'page.js')).href)
    const { select, LoadingScreen, RSVPCard } = await import(pathToFileURL(path.join(dir, 'stubs.js')).href)
    const { begin, runEffects } = await import(pathToFileURL(path.join(dir, 'react.js')).href)
    const pending: { resolve: (response: Response) => void }[] = []
    globalThis.fetch = () => new Promise<Response>(resolve => pending.push({ resolve }))
    const render = (token: string) => {
      select(token)
      const wrapper = Page().props.children.props.children
      const attendee = wrapper.type(wrapper.props)
      begin(attendee.key)
      const result = attendee.type(attendee.props)
      runEffects()
      return result
    }
    const paid = { event: { event_name: 'Same event' }, attendee: { payment: { paid: true, proof: { filename: 'A.webp' } } } }
    const unpaid = { event: { event_name: 'Same event' }, attendee: { payment: { paid: false, proof: null } } }
    assert.equal(render('A').type, LoadingScreen)
    pending[0].resolve(Response.json(paid))
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(render('A').props.data, paid)
    // B's fetch deliberately remains unresolved: no A payment can seed B's card.
    assert.equal(render('B').type, LoadingScreen)
    assert.equal(render('B').type, LoadingScreen)
    pending[1].resolve(Response.json(unpaid))
    await new Promise(resolve => setImmediate(resolve))
    const settled = render('B')
    assert.equal(settled.type, RSVPCard)
    assert.equal(settled.props.token, 'B')
    assert.deepEqual(settled.props.data, unpaid)
  } finally {
    globalThis.fetch = previousFetch
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
