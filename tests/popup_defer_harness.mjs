// Drives the popup-defer pi extension against a fake pi and a fake shared ui.
// Usage: node popup_defer_harness.mjs <config.json>
// config: { script, limits, steps }; prints { results, error } as JSON.
// limits: passed to the extension's register(pi, limits).
// step: { start: ctx, pi } emits session_start on the named fake pi (default main) with a ctx whose ui is the shared fake ui (ctx.mode defaults to "tui").
// step: { key: data, as } sends raw terminal input to every subscribed handler and stores whether one consumed it.
// step: { call: method, args, as } starts a ui call without awaiting it; stores { value, at } once it resolves.
// args: { $signal: name } becomes the AbortSignal of a named controller; { $fn } becomes a function.
// step: { abort: name } aborts a named controller.
// step: { sleep: ms } waits.
// step: { command: name, args, pi } runs a registered slash command.
// step: { shown: as } stores the calls that reached the original ui methods as { method, args, at }.
// step: { notices: as } stores the notify messages. { handlers: as } stores the count of subscribed terminal input handlers.
import { copyFileSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const { script, limits, steps } = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const work = mkdtempSync(join(tmpdir(), 'pi-extension-'))
const name = basename(script)
writeFileSync(join(work, 'package.json'), '{"type":"module"}')
copyFileSync(script, join(work, name))

const started = performance.now()
const elapsed = () => Math.round(performance.now() - started)
const results = {}
const shown = []
const notices = []
const controllers = {}
const handlers = new Set()
const describe = arg => {
  if (typeof arg === 'function') return 'fn'
  if (arg instanceof AbortSignal) return 'signal'
  if (Array.isArray(arg)) return arg.map(describe)
  if (arg && typeof arg === 'object') return Object.fromEntries(Object.entries(arg).map(([key, value]) => [key, describe(value)]))
  return arg
}
const shownMethod = method =>
  function (...args) {
    shown.push({ method, args: describe(args), at: elapsed() })
    return Promise.resolve(`${method}-result`)
  }
const ui = {
  select: shownMethod('select'),
  confirm: shownMethod('confirm'),
  input: shownMethod('input'),
  editor: shownMethod('editor'),
  custom: shownMethod('custom'),
  notify: message => notices.push(message),
  onTerminalInput(handler) {
    handlers.add(handler)
    return () => handlers.delete(handler)
  },
}
const pis = {}
const pi = name => (pis[name ?? 'main'] ??= {
  handlers: {},
  registered: {},
  on(event, handler) { (this.handlers[event] ??= []).push(handler) },
  registerCommand(commandName, options) { this.registered[commandName] = options },
})
const resolve = arg => {
  if (Array.isArray(arg)) return arg.map(resolve)
  if (arg === null || typeof arg !== 'object') return arg
  if ('$signal' in arg) return (controllers[arg.$signal] ??= new AbortController()).signal
  if ('$fn' in arg) return () => {}
  return Object.fromEntries(Object.entries(arg).map(([key, value]) => [key, resolve(value)]))
}

const output = { results }
try {
  const module = await import(pathToFileURL(join(work, name)).href)
  const registered = new Set()
  const fakePi = name => {
    const fake = pi(name)
    if (!registered.has(fake)) module.register(fake, limits)
    registered.add(fake)
    return fake
  }
  for (const step of steps) {
    if (step.start) {
      for (const handler of fakePi(step.pi).handlers.session_start ?? []) await handler({}, { mode: 'tui', ...step.start, ui })
    } else if (step.key !== undefined) {
      let consumed = false
      for (const handler of [...handlers]) consumed = Boolean(handler(step.key)?.consume) || consumed
      if (step.as) results[step.as] = consumed
    } else if (step.call) {
      const { call, args, as } = step
      ui[call](...resolve(args ?? [])).then(value => { if (as) results[as] = { value: value ?? null, at: elapsed() } })
    } else if (step.abort) (controllers[step.abort] ??= new AbortController()).abort()
    else if (step.sleep) await new Promise(done => setTimeout(done, step.sleep))
    else if (step.command) await fakePi(step.pi).registered[step.command].handler(step.args ?? '', { ui })
    else if (step.shown) results[step.shown] = [...shown]
    else if (step.notices) results[step.notices] = [...notices]
    else if (step.handlers) results[step.handlers] = handlers.size
  }
} catch (e) {
  output.error = String(e.stack)
}
process.stdout.write(JSON.stringify(output))
