// Drives the herdr-notify pi extension against a fake pi.
// Usage: node herdr_notify_harness.mjs <config.json>
// config: { script, steps }; prints { results, error } as JSON.
// step: { env: { NAME: value | null } } sets or unsets environment variables of the extension's process.
// step: { emit: event, payload, ctx, as } runs the handlers collected for an event and stores the last result.
// step: { command: name, args, ctx, as } runs a registered slash command; { tool: name, params, ctx, as } runs a registered tool's execute.
// step: { registered: as } stores the registered tools without execute and the registered command names.
// ctx: cwd defaults to /work/project. { "$ui": true } adds a fake ui that records notify messages; { notices: as } stores the [message, level] pairs it was given.
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const { script, steps } = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const work = mkdtempSync(join(tmpdir(), 'pi-extension-'))
const name = basename(script)
const stub = join(work, 'node_modules', 'typebox')
mkdirSync(stub, { recursive: true })
writeFileSync(join(work, 'package.json'), '{"type":"module"}')
writeFileSync(join(stub, 'package.json'), '{"name":"typebox","type":"module","main":"index.js"}')
writeFileSync(
  join(stub, 'index.js'),
  'const make = kind => (...args) => ({ kind, args })\nexport const Type = new Proxy({}, { get: (_target, kind) => make(kind) })\n',
)
const piAi = join(work, 'node_modules', '@earendil-works', 'pi-ai')
mkdirSync(piAi, { recursive: true })
writeFileSync(join(piAi, 'package.json'), '{"name":"@earendil-works/pi-ai","type":"module","main":"index.js"}')
writeFileSync(join(piAi, 'index.js'), "export const StringEnum = (values, options) => ({ kind: 'StringEnum', values, options })\n")
copyFileSync(script, join(work, name))

const results = {}
const notices = []
const handlers = {}
const tools = []
const commands = {}
const pi = {
  on(event, handler) { (handlers[event] ??= []).push(handler) },
  registerTool(tool) { tools.push(tool) },
  registerCommand(command, options) { commands[command] = options },
}
const context = ctx => ({ cwd: '/work/project', ...resolve(ctx ?? {}) })
const resolve = arg => {
  if (Array.isArray(arg)) return arg.map(resolve)
  if (arg === null || typeof arg !== 'object') return arg
  if ('$ui' in arg) return { hasUI: arg.hasUI ?? true, ui: { notify: (message, level) => notices.push([message, level]) } }
  return Object.fromEntries(Object.entries(arg).map(([key, value]) => [key, resolve(value)]))
}

const output = { results }
try {
  const module = await import(pathToFileURL(join(work, name)).href)
  module.default(pi)
  for (const step of steps) {
    let value
    if (step.env) {
      for (const [key, setting] of Object.entries(step.env)) setting === null ? delete process.env[key] : (process.env[key] = setting)
    } else if (step.notices) value = notices
    else if (step.registered) value = { tools: tools.map(({ execute, ...tool }) => tool), commands: Object.keys(commands) }
    else if (step.emit) {
      for (const handler of handlers[step.emit] ?? []) value = (await handler(resolve(step.payload ?? {}), context(step.ctx))) ?? value
    } else if (step.command) value = await commands[step.command].handler(step.args ?? '', context(step.ctx))
    else if (step.tool) value = await tools.find(tool => tool.name === step.tool).execute('call-1', resolve(step.params ?? {}), undefined, undefined, context(step.ctx))
    if (step.as) results[step.as] = value
  }
} catch (e) {
  output.error = String(e.stack)
}
process.stdout.write(JSON.stringify(output))
