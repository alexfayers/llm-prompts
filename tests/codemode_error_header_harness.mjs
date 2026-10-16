// Feeds tool_result events to the codemode-error-header pi extension.
// Usage: node codemode_error_header_harness.mjs <config.json>
// config: { script, events }; prints { results, error } as JSON, one handler result per event.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const { script, events } = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const handlers = {}
const tools = new Proxy(Object.assign(Object.create(null), { real: async (x) => x }), { get: (t, p) => { if (p in t) return t[p]; throw Error(p) } })
const output = {}
try {
  const module = await import(pathToFileURL(script).href)
  module.default({ on: (name, handler) => (handlers[name] ??= []).push(handler) })
  output.results = []
  for (const event of events) {
    const e = { type: 'tool_result', ...event }
    const result = (await handlers[e.type][0](e)) ?? null
    output.results.push(e.type === 'tool_call' ? [e.input.code, await new (async () => {}).constructor('tools', e.input.code)(tools)] : result)
  }
} catch (e) {
  output.error = String(e.stack)
}
process.stdout.write(JSON.stringify(output))
