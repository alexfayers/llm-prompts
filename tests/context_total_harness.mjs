// Runs steps against the exported functions of a pi extension.
// Usage: node context_total_harness.mjs <config.json>
// config: { script, agentDir, steps }; prints { results, error } as JSON.
// step: { fn, args, as } calls an export and stores the result, { append | truncate, text } edits a file.
// step: { sleep: ms } waits.
// step: { utime, seconds } sets a file's access and modification time (Unix seconds).
// step: { emit, pi, payload, ctx, as } runs the handlers a { $pi: name } fake pi collected for an event and stores the last result.
// step: { sent: name, as } stores the [content, options] pairs a fake pi was asked to send as user messages; { $pi: name, commands: [names] } sets the slash commands it reports.
// step: { emitted: name, as } stores the [event, payload] pairs a fake pi's event bus carried; { ui: name, as } stores the [key, text] pairs a fake ui was given to setStatus.
// step: { command, pi, args, ctx } runs a registered slash command handler; { notices: name, as } stores the [message, level] pairs a fake ui was asked to notify.
// step: { call: tool, pi, params, ctx, as } runs a registered tool's execute. { stored: name, as } stores a fake ctx with the paths it switched to and the messages its replacement session sent.
// step: { activeTools: name, as } stores the tool names a fake pi has active; { $pi: name, activeTools: [names] } sets them.
// fake ctx: { $ctx: name, cwd, sessionFile, sessionId } is a command context.
// fake pi: { $pi: name, active: [keys] } answers a zentui:variable-capability probe as active for those keys. { $ui: name } is a fake ui.
// args: { $ref } is a stored result, { $fn } a function returning its value, { $set } a Set, { $map } a Map, { $windows } a window lookup by "provider/model".
import { appendFileSync, copyFileSync, mkdirSync, mkdtempSync, readFileSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const { script, agentDir, steps } = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const work = mkdtempSync(join(tmpdir(), 'pi-extension-'))
const name = basename(script)
const stub = join(work, 'node_modules', '@earendil-works', 'pi-coding-agent')
mkdirSync(stub, { recursive: true })
writeFileSync(join(work, 'package.json'), '{"type":"module"}')
writeFileSync(join(stub, 'package.json'), '{"name":"@earendil-works/pi-coding-agent","type":"module","main":"index.js"}')
writeFileSync(join(stub, 'index.js'), `import { basename, join } from 'node:path'
export const getAgentDir = () => process.env.CONTEXT_TOTAL_AGENT_DIR
export const SessionManager = { forkFrom: (source, target) => ({ getSessionFile: () => join(target, 'fork-of-' + basename(source)) }) }
`)
const typebox = join(work, 'node_modules', 'typebox')
mkdirSync(typebox, { recursive: true })
writeFileSync(join(typebox, 'package.json'), '{"name":"typebox","type":"module","main":"index.js"}')
writeFileSync(join(typebox, 'index.js'), 'export const Type = new Proxy({}, { get: () => () => ({}) })\n')
const piAi = join(work, 'node_modules', '@earendil-works', 'pi-ai')
mkdirSync(piAi, { recursive: true })
writeFileSync(join(piAi, 'package.json'), '{"name":"@earendil-works/pi-ai","type":"module","main":"index.js"}')
writeFileSync(
  join(piAi, 'index.js'),
  `export const getCurrentSystemMessage = messages => {
  const system = messages.filter(message => message.role === 'system')
  if (system.length === 0) return undefined
  const sections = new Map()
  for (const message of system)
    for (const [name, text] of Object.entries(message.sections ?? {})) text === null ? sections.delete(name) : sections.set(name, text)
  return {
    role: 'system',
    content: system.map(message => message.content).filter(Boolean).join('\\n\\n'),
    ...(sections.size > 0 ? { sections: Object.fromEntries(sections) } : {}),
    timestamp: system[0].timestamp,
  }
}
`,
)
copyFileSync(script, join(work, name))
process.env.CONTEXT_TOTAL_AGENT_DIR = agentDir

const results = {}
const pis = {}
const uis = {}
const fakeUi = name => (uis[name] ??= { calls: [], notices: [], setStatus(key, text) { this.calls.push([key, text]) }, notify(message, level) { this.notices.push([message, level]) } })
const ctxs = {}
const fakeCtx = ({ $ctx: name, cwd, sessionFile = join(cwd, 's.jsonl'), sessionId = 'session-id' }) =>
  (ctxs[name] ??= {
    cwd,
    hasUI: true,
    ui: fakeUi(name),
    switched: [],
    continued: [],
    sessionManager: { getSessionId: () => sessionId, getSessionFile: () => sessionFile, usesDefaultSessionDir: () => true },
    async switchSession(path, options) {
      this.switched.push(path)
      await options?.withSession?.({ sendUserMessage: async (...args) => this.continued.push(args) })
      return { cancelled: false }
    },
  })
const fakePi = (name, commands = [], active = [], activeTools = []) => {
  pis[name] ??= {
    handlers: {},
    sent: [],
    commands,
    activeTools,
    emitted: [],
    registered: {},
    events: {
      emit(event, payload) {
        const pi = pis[name]
        pi.emitted.push([event, JSON.parse(JSON.stringify(payload))])
        if (event === 'zentui:variable-capability' && active.includes(payload.key)) payload.active = true
      },
    },
    tools: {},
    registerTool(tool) { this.tools[tool.name] = tool },
    registerCommand(name, options) { this.registered[name] = options },
    on(event, handler) { (this.handlers[event] ??= []).push(handler) },
    getActiveTools() { return this.activeTools },
    setActiveTools(names) { this.activeTools = names },
    getCommands() { return this.commands.map(name => ({ name })) },
    async sendUserMessage(...args) { this.sent.push(args) },
  }
  return pis[name]
}
const resolve = arg => {
  if (Array.isArray(arg)) return arg.map(resolve)
  if (arg === null || typeof arg !== 'object') return arg
  if ('$pi' in arg) return fakePi(arg.$pi, arg.commands, arg.active, arg.activeTools)
  if ('$ctx' in arg) return fakeCtx(arg)
  if ('$ui' in arg) return fakeUi(arg.$ui)
  if ('$ref' in arg) return results[arg.$ref]
  if ('$set' in arg) return new Set(arg.$set)
  if ('$fn' in arg) return () => resolve(arg.$fn)
  if ('$map' in arg) return new Map(arg.$map)
  if ('$windows' in arg) return (provider, model) => arg.$windows[`${provider}/${model}`]
  return Object.fromEntries(Object.entries(arg).map(([key, value]) => [key, resolve(value)]))
}

const output = { results }
try {
  const module = await import(pathToFileURL(join(work, name)).href)
  for (const step of steps) {
    if (step.append) appendFileSync(step.append, step.text)
    else if (step.truncate) writeFileSync(step.truncate, step.text)
    else if (step.sleep) await new Promise(done => setTimeout(done, step.sleep))
    else if (step.utime) utimesSync(step.utime, step.seconds, step.seconds)
    else if (step.emitted) results[step.as] = pis[step.emitted].emitted
    else if (step.ui) results[step.as] = uis[step.ui].calls
    else if (step.notices) results[step.as] = uis[step.notices].notices
    else if (step.stored) results[step.as] = ctxs[step.stored]
    else if (step.call) results[step.as] = await pis[step.pi].tools[step.call].execute('call-id', resolve(step.params ?? {}), undefined, undefined, resolve(step.ctx ?? {}))
    else if (step.command) await pis[step.pi].registered[step.command].handler(step.args ?? '', resolve(step.ctx ?? {}))
    else if (step.activeTools) results[step.as] = pis[step.activeTools].activeTools
    else if (step.sent) results[step.as] = pis[step.sent].sent
    else if (step.emit) {
      let value
      for (const handler of pis[step.pi].handlers[step.emit] ?? []) value = (await handler(resolve(step.payload ?? {}), resolve(step.ctx ?? {}))) ?? value
      if (step.as) results[step.as] = value
    } else {
      const value = await module[step.fn](...resolve(step.args ?? []))
      if (step.as) results[step.as] = value
    }
  }
} catch (e) {
  output.error = String(e.stack)
}
process.stdout.write(JSON.stringify(output, (_key, value) => (value instanceof Set ? [...value] : value)))
