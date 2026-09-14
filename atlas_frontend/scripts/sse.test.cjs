const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { pathToFileURL } = require('node:url')
const ts = require('typescript')

const compiled = ts.transpileModule(
  fs.readFileSync(new URL('../src/lib/sse.ts', pathToFileURL(__filename)), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText

function stream(parts, keepOpen = false) {
  let cancelled = false
  const body = new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(new TextEncoder().encode(part))
      if (!keepOpen) controller.close()
    },
    cancel() { cancelled = true },
  })
  const context = { exports: {}, TextDecoder, Error, fetch: async () => ({ ok: true, body }) }
  vm.runInNewContext(compiled, context)
  return { events: context.exports.postEventStream('/api/chat', {}), cancelled: () => cancelled }
}

test('SSE preserves events across chunks and CRLF delimiters', async () => {
  const s = stream([': ready\r\n\r\ndata: {"text":"café"}\r', '\n\r', '\ndata: {"done":true}\n\n'])
  const events = []
  for await (const event of s.events) events.push(event)
  assert.equal(JSON.stringify(events), '[{"text":"café"},{"done":true}]')
})

test('SSE reports a truncated event instead of silently dropping it', async () => {
  const s = stream(['data: {"text":"unfinished'])
  await assert.rejects(async () => { for await (const event of s.events) void event }, /mid-event/)
})

test('SSE cancels the transport when a consumer stops reading', async () => {
  const s = stream(['data: {"text":"first"}\n\n'], true)
  for await (const event of s.events) { assert.equal(event.text, 'first'); break }
  assert.equal(s.cancelled(), true)
})
