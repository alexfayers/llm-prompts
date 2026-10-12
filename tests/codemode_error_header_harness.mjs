// Feeds tool_result events to the codemode-error-header pi extension.
// Usage: node codemode_error_header_harness.mjs <config.json>
// config: { script, events }; prints { results, error } as JSON, one handler result per event.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const { script, events } = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const handlers = {}
const output = {}
try {
  const module = await import(pathToFileURL(script).href)
  module.default({ on: (name, handler) => (handlers[name] ??= []).push(handler) })
  output.results = []
  for (const event of events) {
    output.results.push((await handlers.tool_result[0]({ type: 'tool_result', ...event })) ?? null)
  }
} catch (e) {
  output.error = String(e.stack)
}
process.stdout.write(JSON.stringify(output))
