// Runs the eagle-vision build-wave workflow script against fake agents.
// Usage: node build_wave_harness.mjs <config.json>
// config: { script, args, scenario }; prints { result, error, calls } as JSON.
// scenario.shell and scenario.stub map a runner label (or its part before ":") to the marker
// lines the script would print, or to a list of such lists for successive calls.
// shell replaces every runner script (an unmapped label is an error), stub only the mapped labels.
import { spawn } from 'node:child_process'
import { closeSync, existsSync, openSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor
const MAX_WAITS = 6

const { script, args, scenario = {} } = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const source = readFileSync(script, 'utf8').replace('export const meta', 'const meta')
const calls = []
const errors = []

const logSize = file => (existsSync(file) ? statSync(file).size : 0)

const COMMAND = /^cd (\S+) && bash (\S+\.sh)(?: (\S+))? (>>?) (\S+\.log) 2>&1$/

const exec = ([, cwd, file, step, mode, log]) => new Promise(resolve => {
  const out = openSync(log, mode === '>' ? 'w' : 'a')
  spawn('bash', step ? [file, step] : [file], { cwd, stdio: ['ignore', out, out] })
    .on('error', () => resolve(1))
    .on('close', code => { closeSync(out); resolve(code ?? 1) })
})

const runCommand = async (command, repeat) => {
  const parts = command.match(COMMAND)
  const log = parts[5]
  const waiting = repeat && parts[3] === 'wait' ? new RegExp(`^${repeat}`, 'm') : null
  for (let waits = 0; waits <= MAX_WAITS; waits++) {
    const before = logSize(log)
    const code = await exec(parts)
    if (code !== 0 || !waiting?.test(readFileSync(log, 'utf8').slice(before))) return code
  }
  return 0
}

const replayed = {}

const scriptedKey = (label, replies) => [label, label.split(':')[0]].find(k => k in replies)

const scripted = (label, replies) => {
  const key = scriptedKey(label, replies)
  if (key === undefined) throw new Error(`runner call without scripted lines: ${label}`)
  const reply = replies[key]
  if (!Array.isArray(reply[0])) return reply
  replayed[key] = (replayed[key] ?? -1) + 1
  return reply[Math.min(replayed[key], reply.length - 1)]
}

const runner = async (prompt, label) => {
  const prefixes = [...prompt.match(/starts with (.*), verbatim/)[1].matchAll(/"([^"]*)"/g)].map(m => m[1])
  const replies = scenario.shell ?? (scriptedKey(label, scenario.stub ?? {}) === undefined ? null : scenario.stub)
  if (replies) return { lines: scripted(label, replies).filter(l => prefixes.some(p => l.startsWith(p))) }
  const file = prompt.match(/to (\S+\.sh) with the Write tool/)[1]
  const commands = [...prompt.matchAll(/^ {3}(cd \S+ && bash .*)$/gm)].map(m => m[1])
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(file, `${prompt.slice(prompt.indexOf('\n\n', prompt.indexOf('3. Read')) + 2)}\n`)
  const repeat = prompt.match(/while it prints a line starting with "(\w+)"/)?.[1]
  for (const command of commands) if (await runCommand(command, repeat) !== 0) break
  const log = `${file.replace(/\.sh$/, '')}.log`
  const lines = existsSync(log) ? readFileSync(log, 'utf8').split('\n').filter(l => prefixes.some(p => l.startsWith(p))) : []
  return { lines }
}

const writeFiles = (dir, files = {}) => {
  for (const [rel, content] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, rel)), { recursive: true })
    writeFileSync(join(dir, rel), content)
  }
  return Object.keys(files)
}

const worker = (label, prompt) => {
  const kind = label.match(/^[a-z]+/)[0]
  if (kind === 'resolve') return { status: 'skipped', note: 'cannot resolve' }
  if (kind === 'triage') return scenario.triage || { failures: [] }
  const [, id, pkgDir] = prompt.match(/plan node (\S+) in (\/[^\s;,()]+)/)
  const slug = id.split('/').pop()
  const defaults = { tests: { [`tests/test_${slug}.py`]: 'ok\n' }, impl: { [`src/${slug}.txt`]: 'impl\n' }, fix: {} }
  const spec = scenario[kind]?.[slug] || {}
  const files = writeFiles(pkgDir, spec.files || defaults[kind])
  return kind === 'tests' ? { files, notes: spec.notes } : { status: spec.status || 'done', note: spec.note || '', files }
}

const agent = async (prompt, opts) => {
  calls.push({ label: opts.label, agentType: opts.agentType, prompt })
  return opts.agentType === 'eagle-vision-runner-haiku-low' ? runner(prompt, opts.label) : worker(opts.label, prompt)
}

const pipeline = (items, first, ...rest) => Promise.all(items.map(async item => {
  try {
    let previous = await first(item)
    for (const stage of rest) previous = await stage(previous, item)
    return previous
  } catch (e) {
    errors.push(String(e.stack))
    return null
  }
}))

const output = {}
try {
  output.result = await new AsyncFunction('args', 'agent', 'pipeline', 'phase', 'log', source)(args, agent, pipeline, () => {}, () => {})
} catch (e) {
  output.error = e.message
}
process.stdout.write(JSON.stringify({ ...output, errors, calls }))
