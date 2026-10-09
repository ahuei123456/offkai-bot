import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import type { ReactElement, ReactNode } from 'react'

const tick = () => new Promise<void>(resolve => setImmediate(resolve))

test('actual admin payment control supports confirmed cash override and private preview cleanup/races', async () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.payment-control-test-'))
  const previousFetch = globalThis.fetch
  const previousCreate = URL.createObjectURL
  const previousRevoke = URL.revokeObjectURL
  const originalWindow = globalThis.window
  try {
    fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
    fs.writeFileSync(path.join(dir, 'react.js'), `
      const states=[]; let index=0; let effects=[]; let cleanup;
      export function begin(){index=0;effects=[];}
      export function useState(initial){const key=index++;if(!(key in states))states[key]=initial;
        return [states[key],value=>{states[key]=typeof value==='function'?value(states[key]):value;}];}
      export function useEffect(fn){effects.push(fn);}
      export function runEffects(){if(cleanup)cleanup();for(const fn of effects)cleanup=fn();}
      export function unmount(){if(cleanup)cleanup();}
    `)
    fs.writeFileSync(path.join(dir, 'i18n.js'), `export function useT(){return {t:{
      confirmPaidWithoutProof:'Confirm cash payment',markPaid:'Mark paid',markUnpaid:'Mark unpaid',
      waitingForProof:'Waiting for proof',previewProof:'Preview proof',paid:'Paid',paymentPending:'Pending',
      paymentProof:'Proof',paymentSaveError:'Save error',paymentPreviewError:'Preview error'}};}`)
    const source = fs.readFileSync(path.join(process.cwd(), 'app/components/admin/PaymentControl.tsx'), 'utf8')
    const code = ts.transpileModule(source, { compilerOptions: {
      module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
    } }).outputText.replaceAll("from 'react'", "from './react.js'").replaceAll("from '../../lib/i18n'", "from './i18n.js'")
    fs.writeFileSync(path.join(dir, 'control.js'), code)
    const { begin, runEffects, unmount } = await import(pathToFileURL(path.join(dir, 'react.js')).href)
    const { PaymentControl } = await import(pathToFileURL(path.join(dir, 'control.js')).href)
    function elements(node: ReactNode, type: string): ReactElement<Record<string, unknown>>[] {
      if (Array.isArray(node)) return node.flatMap(child => elements(child, type))
      if (!node || typeof node !== 'object' || !('type' in node) || !('props' in node)) return []
      const element = node as ReactElement<Record<string, unknown>>
      return [...(element.type === type ? [element] : []), ...elements(element.props.children as ReactNode, type)]
    }
    const calls: unknown[] = []
    let confirm = false
    globalThis.window = { confirm: () => confirm } as unknown as Window & typeof globalThis
    const attendee = { user_id: '191524132624531458', payment_enabled: true, registration_timestamp: '2026-10-01T00:00:00Z',
      payment: { paid: false, proof: null } }
    const render = (proof: { filename: string; uploaded_at: string } | null = null) => {
      begin()
      return PaymentControl({ attendee: { ...attendee, payment: { paid: false, proof } },
        adminKey: 'synthetic-test-key', eventName: 'Test event', onPayment: async (...args: unknown[]) => { calls.push(args); return true } })
    }
    let tree = render()
    assert.equal(elements(tree, 'details')[0].props.open, undefined)
    let paid = elements(tree, 'button').find(button => button.props.children === 'Mark paid')!
    await (paid.props.onClick as () => Promise<void>)()
    assert.deepEqual(calls, [])
    confirm = true
    await (paid.props.onClick as () => Promise<void>)()
    assert.deepEqual(calls, [[attendee.user_id, true, attendee.registration_timestamp]])
    const requests: { url: string; options: RequestInit; resolve: (r: Response) => void }[] = []
    globalThis.fetch = (async (url, options) => new Promise<Response>(resolve => requests.push({ url: String(url), options: options!, resolve }))) as typeof fetch
    let nextUrl = 0
    const revoked: string[] = []
    URL.createObjectURL = () => `blob:synthetic-${++nextUrl}`
    URL.revokeObjectURL = url => revoked.push(url)
    const firstProof = { filename: 'a.webp', uploaded_at: '2026-10-02T00:00:00Z' }
    tree = render(firstProof)
    const preview = elements(tree, 'button').find(button => button.props.children === 'Preview proof')!
    ;(preview.props.onClick as () => void)()
    render(firstProof)
    runEffects()
    assert.equal(requests.length, 1)
    assert.equal(new URL(requests[0].url, 'http://localhost').searchParams.has('key'), false)
    assert.equal(new Headers(requests[0].options.headers).get('authorization'), 'Bearer synthetic-test-key')
    const previewParams = new URL(requests[0].url, 'http://localhost').searchParams
    assert.equal(previewParams.get('registration_timestamp'), attendee.registration_timestamp)
    assert.equal(previewParams.get('proof_filename'), firstProof.filename)
    const secondProof = { filename: 'b.webp', uploaded_at: '2026-10-03T00:00:00Z' }
    render(secondProof)
    runEffects()
    assert.equal(requests[0].options.signal?.aborted, true)
    requests[1].resolve(new Response('new image'))
    await tick()
    requests[0].resolve(new Response('old image'))
    await tick()
    tree = render(secondProof)
    assert.equal(elements(tree, 'img')[0].props.src, 'blob:synthetic-1')
    assert.equal(nextUrl, 1)
    unmount()
    assert.deepEqual(revoked, ['blob:synthetic-1'])
  } finally {
    globalThis.fetch = previousFetch
    URL.createObjectURL = previousCreate
    URL.revokeObjectURL = previousRevoke
    if (originalWindow === undefined) delete (globalThis as { window?: Window }).window; else globalThis.window = originalWindow
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('actual removal confirmation targets the displayed signup and shows changed-registration feedback', async () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), 'node_modules', '.removal-control-test-'))
  const previousWindow = globalThis.window
  try {
    fs.writeFileSync(path.join(dir, 'package.json'), '{"type":"module"}')
    fs.writeFileSync(path.join(dir, 'react.js'), `const states=[];let index=0;
      export function begin(){index=0;}
      export function useState(initial){const key=index++;if(!(key in states))states[key]=initial;
        return [states[key],value=>states[key]=value];}`)
    fs.writeFileSync(path.join(dir, 'i18n.js'), `export function useT(){return {t:{removeUser:'Remove',
      confirmRemove:name=>'Remove '+name,removalRegistrationChanged:'Registration changed',
      removalNotStarted:'Not removed',removalError:'Unconfirmed'}};}`)
    const code = ts.transpileModule(fs.readFileSync('app/components/admin/RemoveRegistration.tsx', 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText.replaceAll("from 'react'", "from './react.js'").replaceAll("from '../../lib/i18n'", "from './i18n.js'")
    fs.writeFileSync(path.join(dir, 'control.js'), code)
    const { begin } = await import(pathToFileURL(path.join(dir, 'react.js')).href)
    const { RemoveRegistration } = await import(pathToFileURL(path.join(dir, 'control.js')).href)
    const attendee = { user_id: '191524132624531458', username: 'Original signup',
      registration_timestamp: '2026-10-01T00:00:00.000Z' }
    const calls: unknown[] = []
    let confirm = false
    globalThis.window = { confirm: () => confirm } as unknown as Window & typeof globalThis
    const render = () => { begin(); return RemoveRegistration({ attendee,
      onRemove: async (...args: unknown[]) => { calls.push(args); throw new Error('registration_changed') } }) }
    let tree = render()
    const click = tree.props.children[0].props.onClick
    await click()
    assert.deepEqual(calls, [])
    confirm = true
    await click()
    assert.deepEqual(calls, [[attendee.user_id, attendee.registration_timestamp]])
    tree = render()
    assert.equal(tree.props.children[1].props.role, 'alert')
    assert.equal(tree.props.children[1].props.children, 'Registration changed')
    assert.equal(tree.props.children[0].props.disabled, false)
  } finally {
    globalThis.window = previousWindow
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
