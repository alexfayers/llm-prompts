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
const ids = Object.keys(args.nodes)
const verdicts = await parallel(ids.map(id => () =>
  agent(`${args.plan}\n${args.nodes[id]}`, {
    label: `check:${id}`,
    phase: 'Check',
    schema: BLOCKERS,
    agentType: 'eagle-vision-checker-haiku-low',
  })))
const blocked = ids
  .map((node, i) => ({ node, blockers: verdicts[i]?.blockers }))
  .filter(v => v.blockers?.length)
const unchecked = ids.filter((_, i) => !verdicts[i])
log(`${ids.length - blocked.length - unchecked.length}/${ids.length} nodes have no blockers`)
return { blocked, unchecked }
