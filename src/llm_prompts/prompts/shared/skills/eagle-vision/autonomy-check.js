export const meta = {
  name: 'eagle-vision-autonomy-check',
  description: 'Judge each eagle-vision node brief with a plan-only checker; return only nodes with blockers',
  phases: [{ title: 'Check' }],
}

const BLOCKERS = {
  type: 'object',
  properties: {
    blockers: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          kind: { type: 'string', enum: ['contradiction', 'missing-input', 'user-decision'] },
          reason: { type: 'string' },
        },
        required: ['kind', 'reason'],
      },
    },
  },
  required: ['blockers'],
}

phase('Check')
const verdicts = await parallel(args.map(path => () =>
  agent(`Read only the file ${path} (in chunks if needed). It holds a plan and one node's brief. Judge that node.`, {
    label: `check:${path}`,
    phase: 'Check',
    schema: BLOCKERS,
    agentType: 'eagle-vision-checker-haiku-low',
  })))
const blocked = args
  .map((node, i) => ({ node, blockers: verdicts[i]?.blockers }))
  .filter(v => v.blockers?.length)
const unchecked = args.filter((_, i) => !verdicts[i])
log(`${args.length - blocked.length - unchecked.length}/${args.length} nodes have no blockers`)
return { blocked, unchecked }
