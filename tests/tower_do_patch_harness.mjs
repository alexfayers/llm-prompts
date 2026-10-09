// Runs steps against the exported functions of the tower-do-patch pi extension.
// Usage: node tower_do_patch_harness.mjs <config.json>
// config: { script, steps }; prints { results, error } as JSON.
// step: { fn, args, as, catch } calls an export and stores the result; with catch, a throw is stored as { threw: message }.
// step: { register: { $pi } } runs the extension's default export against a fake pi; { call: tool, pi, params, ctx, as, catch } runs a registered tool's execute; { registered: name, as } stores the registered tools without their execute.
// step: { writes: name, as } stores the arguments a { $deps } fake was asked to write; { calls: name, as } stores the [tool, args] pairs a { $ctx } fake was asked to execute.
// args: { $ref } is a stored result, { $deps: { boards, outcomes }, name } is fake patch dependencies: readBoard answers the boards in turn (the last repeats), write records its arguments and answers the outcomes in turn.
// fake pi: { $pi: name, board: { revision, keys } } reports a tower_do tool whose board.ts folds to that board.
// fake ctx: { $ctx: name, outcomes } answers executeTool("tower_do_status") with a board file path and executeTool("tower_do") with the outcomes in turn.
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs'
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
copyFileSync(script, join(work, name))

const results = {}
const deps = {}
const pis = {}
const ctxs = {}
const fakeDeps = (key, spec) =>
  (deps[key] ??= {
    writes: [],
    boardReads: 0,
    async readBoard() {
      const boards = spec.boards
      return boards[Math.min(this.boardReads++, boards.length - 1)]
    },
    async write(args) {
      this.writes.push(JSON.parse(JSON.stringify(args)))
      const outcomes = spec.outcomes
      return outcomes[Math.min(this.writes.length - 1, outcomes.length - 1)]
    },
  })
const fakePi = ({ $pi: name, board }) =>
  (pis[name] ??= {
    tools: [],
    registerTool(tool) { this.tools.push(tool) },
    getAllTools() {
      if (!board) return []
      const dir = join(work, 'tower-do')
      mkdirSync(dir, { recursive: true })
      writeFileSync(
        join(dir, 'board.ts'),
        `export class TowerBoard {\n  constructor(file) { this.file = file }\n  async fold() { return { revision: ${board.revision}, tasks: ${JSON.stringify(board.keys.map(key => ({ key })))} } }\n}\n`,
      )
      return [{ name: 'tower_do', sourceInfo: { path: join(dir, 'index.ts') } }]
    },
  })
const fakeCtx = ({ $ctx: name, outcomes }) =>
  (ctxs[name] ??= {
    calls: [],
    async executeTool(tool, args) {
      this.calls.push([tool, JSON.parse(JSON.stringify(args))])
      if (tool === 'tower_do_status') return { isError: false, result: { content: [], details: { board: '/boards/board.jsonl' } } }
      return outcomes[Math.min(this.calls.filter(([t]) => t === 'tower_do').length - 1, outcomes.length - 1)]
    },
  })
const resolve = arg => {
  if (Array.isArray(arg)) return arg.map(resolve)
  if (arg === null || typeof arg !== 'object') return arg
  if ('$ref' in arg) return results[arg.$ref]
  if ('$deps' in arg) return fakeDeps(arg.name, arg.$deps)
  if ('$pi' in arg) return fakePi(arg)
  if ('$ctx' in arg) return fakeCtx(arg)
  return Object.fromEntries(Object.entries(arg).map(([key, value]) => [key, resolve(value)]))
}
const attempt = async (step, run) => {
  try {
    return await run()
  } catch (e) {
    if (!step.catch) throw e
    return { threw: e.message }
  }
}

const output = { results }
try {
  const module = await import(pathToFileURL(join(work, name)).href)
  for (const step of steps) {
    if (step.calls) results[step.as] = ctxs[step.calls].calls
    else if (step.writes) results[step.as] = deps[step.writes].writes
    else if (step.registered) results[step.as] = pis[step.registered].tools.map(({ execute, ...tool }) => tool)
    else if (step.register) module.default(resolve(step.register))
    else if (step.call) {
      const tool = pis[step.pi].tools.find(t => t.name === step.call)
      const value = await attempt(step, () => tool.execute('id', step.params, undefined, undefined, resolve(step.ctx)))
      if (step.as) results[step.as] = value
    } else {
      const value = await attempt(step, () => module[step.fn](...resolve(step.args ?? [])))
      if (step.as) results[step.as] = value
    }
  }
} catch (e) {
  output.error = String(e.stack)
}
process.stdout.write(JSON.stringify(output))
