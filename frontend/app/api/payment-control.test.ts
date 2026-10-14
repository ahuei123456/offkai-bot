import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
// Render the real JSX component with its real English translation context.
for (const extension of ['.tsx', '.ts']) {
  require.extensions[extension] = (module, filename) => {
    const output = ts.transpileModule(readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    ;(module as unknown as { _compile: (code: string, filename: string) => void })._compile(output, filename)
  }
}
const { createElement } = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { PaymentControl } = require('../components/admin/PaymentControl.tsx')

function render(method: string | null, paid = false, proof: object | null = null) {
  return renderToStaticMarkup(createElement(PaymentControl, {
    attendee: { user_id: '1', payment_enabled: true, payment_method: method, payment: { paid, proof } },
    adminKey: 'test', eventName: 'test', onPayment: async () => true,
  }))
}

test('pending proof exposes the chosen method without marking payment paid', () => {
  const html = render('Bank transfer')
  assert.match(html, /Pending payment proof/)
  assert.match(html, /Bank transfer/)
  assert.match(html, /Mark paid/)
  assert.doesNotMatch(html, /Mark unpaid/)
})

test('missing method never invents a payment choice', () => {
  const html = render(null)
  assert.match(html, /Pending payment proof/)
  assert.doesNotMatch(html, /font-normal/)
})

test('method labels are escaped and remain visible for paid and uploaded proof states', () => {
  for (const html of [render('<Bank>'), render('Cash', true), render('Card', false, { filename: 'proof.jpg' })]) {
    assert.match(html, /font-normal/)
    assert.doesNotMatch(html, /<Bank>/)
  }
  assert.match(render('<Bank>'), /&lt;Bank&gt;/)
})
