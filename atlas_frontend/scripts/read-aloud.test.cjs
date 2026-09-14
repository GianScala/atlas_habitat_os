/** Local playback lifecycle tests without a browser, microphone, or network. */
const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { pathToFileURL } = require('node:url')
const ts = require('typescript')

const compiled = ts.transpileModule(
  fs.readFileSync(new URL('../src/lib/readAloud.ts', pathToFileURL(__filename)), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText

function player(synthesize = async () => ({})) {
  const sounds = []
  let denied = false
  class Audio {
    constructor() { sounds.push(this); this.paused = true }
    async play() {
      if (denied) throw new DOMException('blocked', 'NotAllowedError')
      this.paused = false
    }
    pause() { this.paused = true }
    removeAttribute() {}
    load() {}
  }
  const context = {
    exports: {}, Audio, AbortController, DOMException, Error,
    URL: { createObjectURL: () => 'blob:local', revokeObjectURL: () => {} },
    require: (name) => name === 'react'
      ? { useSyncExternalStore: (_subscribe, snapshot) => snapshot() }
      : { synthesizeVoice: synthesize },
  }
  vm.runInNewContext(compiled, context)
  return { ...context.exports, sounds, deny: (value) => { denied = value } }
}
const tick = () => new Promise((resolve) => setImmediate(resolve))

test('all response text survives chunking, including decimals and negative values', () => {
  const p = player()
  const text = ('Temperature -2.5 C. Water 120.75 L. ').repeat(600).trim()
  const chunks = p.speechChunks(text)
  assert.ok(chunks.every((chunk) => chunk.length <= 700))
  assert.equal(chunks.join(' '), text)
})

test('autoplay refusal is visible and can resume with a tap', async () => {
  const p = player()
  p.deny(true)
  p.readAloud('answer', 'Water use is 12 litres.')
  await tick()
  assert.equal(p.useReadAloud().phase, 'blocked')
  p.deny(false)
  await p.resumeReadAloud()
  assert.equal(p.useReadAloud().phase, 'playing')
  p.stopReadAloud()
  assert.equal(p.sounds[0].paused, true)
})

test('cancelling pending synthesis prevents late playback', async () => {
  let resolve
  const p = player(() => new Promise((done) => { resolve = done }))
  p.readAloud('answer', 'A local answer.')
  p.stopReadAloud()
  resolve({})
  await tick()
  assert.equal(p.sounds.length, 0)
  assert.equal(p.useReadAloud().phase, 'idle')
})

test('starting another answer stops the first and reports actionable errors', async () => {
  let fail = false
  const p = player(async () => { if (fail) throw new Error('Voice model missing'); return {} })
  p.readAloud('one', 'First answer.')
  await tick()
  assert.equal(p.useReadAloud().phase, 'playing')
  fail = true
  p.readAloud('two', 'Second answer.')
  await tick()
  assert.equal(p.sounds[0].paused, true)
  assert.equal(p.useReadAloud().error, 'Voice model missing')
})

test('long answers proceed to the next audio chunk on completion', async () => {
  let calls = 0
  const p = player(async () => { calls += 1; return {} })
  p.readAloud('long', 'Telemetry is available. '.repeat(100))
  await tick()
  p.sounds[0].onended()
  await tick()
  assert.equal(calls, 2)
  assert.equal(p.sounds[0].paused, true)
  assert.equal(p.useReadAloud().phase, 'playing')
})
