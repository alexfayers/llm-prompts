export const meta = {
  name: 'eagle-vision-build-wave',
  description: 'Build one wave of an eagle-vision plan: a git worktree per node, tests, implementation, bounded gate retries, then merge onto the target branch and check-wave',
  whenToUse: 'Build an eagle-vision plan one wave at a time; args = {plan, skill, wave, stamp}, or {plan, skill, wave, stamp, probeOnly}, or {plan, skill, wave, stamp, resume, rebuild} to finish a wave from its existing worktrees; plan is the absolute plan dir (the parent dir on multi-repo plans), skill the absolute eagle-vision skill dir, stamp a new unique string per run, never use resumeFromRunId',
  phases: [
    { title: 'Scout', detail: 'list the wave nodes' },
    { title: 'Setup', detail: 'one probe worktree per dir proves deps, build, smoke and the lint baseline; one node worktree per node, created in parallel' },
    { title: 'Build', detail: 'test writer, implementer, gate fixers' },
    { title: 'Gate', detail: 'sync, deps, build, new-lint check and focus.py check --node-only per node' },
    { title: 'Merge', detail: 'rebase + fast-forward onto the target branch, wave build, check-wave per touched dir' },
    { title: 'Triage', detail: 'classify red checks; regressions and plan defects escalate' },
  ],
}

const ARGS = args !== null && typeof args === 'object' ? args : { wave: args }
const WAVE = Number(ARGS.wave)
const PLAN = ARGS.plan
const SKILL = ARGS.skill
const STAMP = ARGS.stamp
const PROBE_ONLY = ARGS.probeOnly === true
const RESUME = ARGS.resume === true
const REBUILD = ARGS.rebuild || []
const PATH_RE = /^(\/[A-Za-z0-9._-]+)+$/
if (!Number.isInteger(WAVE) || WAVE < 1 || ![PLAN, SKILL].every(p => typeof p === 'string' && PATH_RE.test(p)) || typeof STAMP !== 'string' || !/^[A-Za-z0-9._-]+$/.test(STAMP)) throw new Error(`args must be {plan, skill, wave, stamp}, {plan, skill, wave, stamp, probeOnly} or {plan, skill, wave, stamp, resume, rebuild}, plan and skill absolute paths, stamp a unique [A-Za-z0-9._-] string; got ${JSON.stringify(args)}`)

const FOCUS = `python3 "${SKILL}/focus.py"`
const ROOT = `/tmp/eagle-vision${PLAN}`
const LOGS = `${ROOT}/wave-${WAVE}/${STAMP}`
const MAX_FIX_ROUNDS = 2
const MAX_TEST_ATTEMPTS = 2
const DEFAULT_BUILD_CAP = 4
const IDLE_LOW = 10
const IDLE_HIGH = 30
const WAIT_SECONDS = 540
const POLL_SECONDS = 1
const MAX_WAITS = 6
const MAX_DETAILS = 15
const RUNNER = 'eagle-vision-runner-haiku-low'
const ERR_RE = '^(FAIL|FAILED|ERROR)[ :]|: error:|Error:|error TS[0-9]+'
const TEST_PATH_RE = '[ /](tests?|tst|__tests__)/|[ /]test_[^/ ]+[.]py|_test[.](py|go)$|[.](test|spec)[.][jt]sx?$'
const NODE_RE = /^([a-z0-9-]+\/)?[a-z0-9-]+$/
const GATE_STEPS = ['sync', 'deps', 'build', 'lint', 'check', 'commit']
const PROBE_STEPS = ['add', 'sync', 'deps', 'build', 'smoke', 'baseline']
const TESTS_STEPS = ['files', 'build', 'collect']
const SHORT_STEPS = ['add', 'sync', 'commit', 'files', 'collect']
const nextBuildCap = (idle, cap, max) => !/^\d+$/.test(idle) ? cap : idle < IDLE_LOW ? Math.max(1, cap - 1) : idle > IDLE_HIGH ? Math.min(max, cap + 1) : cap
const isLongStep = s => !SHORT_STEPS.includes(s)
const withWaits = steps => steps.flatMap(s => isLongStep(s) ? [s, 'wait'] : [s])

const STR = { type: 'string' }
const STRS = { type: 'array', items: STR }
const DENIED = { type: 'string', description: 'verbatim permission-denial text; empty if none' }
const obj = (properties, required) => ({ type: 'object', properties, required })
const MARKERS = obj({ lines: STRS, denied: DENIED }, ['lines'])
const TESTS = obj({ files: STRS, notes: STR, denied: DENIED }, ['files'])
const IMPL = obj({ status: { type: 'string', enum: ['done', 'blocked'] }, note: STR, files: STRS, denied: DENIED }, ['status', 'note'])
const RESOLVE = obj({ status: { type: 'string', enum: ['resolved', 'skipped'] }, note: STR, files: STRS, denied: DENIED }, ['status', 'note'])
const TRIAGE = obj({ failures: { type: 'array', items: obj({ dir: STR, test: STR, kind: { type: 'string', enum: ['unbuilt', 'regression', 'plan-defect'] }, node: STR, laterNode: STR, fix: STR }, ['dir', 'test', 'kind', 'fix']) }, denied: DENIED }, ['failures'])

const makeNode = id => {
  const [dir, slug] = id.includes('/') ? id.split('/') : ['.', id]
  return { id, dir, slug, name: dir === '.' ? `ev${WAVE}-${slug}` : `ev${WAVE}-${dir}-${slug}` }
}
const probeOf = dir => ({ dir, name: dir === '.' ? 'ev-probe' : `ev-probe-${dir}` })
const nodeFile = (n, stage = '') => `${PLAN}/${n.dir}/nodes/${stage && `${stage}/`}${n.slug}.md`
const pkgDirOf = n => `$(ev_pkg ${n.name} ${n.dir})`

// ---- Shell prelude: the hooks a plan's build.sh may override, then shared functions ----

const HOOKS = [
  `EV_PLAN="${PLAN}"; EV_ROOT="${ROOT}"`,
  '# EV_TARGET: the branch nodes merge onto, in every repo',
  'EV_TARGET=main',
  '# EV_LINT_RE: matches a lint finding line, <path>:<line>[:<col>]: <message>',
  "EV_LINT_RE='^[^ :]+:[0-9]+(:[0-9]+)?: '",
  '# ev_repo <dir>: print the main checkout path of plan dir <dir> (. for a bare node id)',
  'ev_repo() { ( cd "$EV_PLAN/$1" && git rev-parse --show-toplevel ); }',
  '# ev_worktree_add <name> <dir>: create the node worktree at $EV_TARGET unless it exists',
  'ev_worktree_add() { local r; r=$(ev_repo "$2") || return 1; [ -d "$r-ev/$1" ] || ( cd "$r" && git worktree add -q -b "ev/$1" "$r-ev/$1" "$EV_TARGET" ); }',
  '# ev_worktree_paths <name> <dir>: print one "<label> <path>" line per checkout, the node\'s own first',
  'ev_worktree_paths() { echo "$2 $(ev_repo "$2")-ev/$1"; }',
  '# ev_worktree_remove <name> <dir>: remove the node worktree and its branch',
  'ev_worktree_remove() { local r; r=$(ev_repo "$2") || return 1; ( cd "$r" && git worktree remove "$r-ev/$1" && git branch -d "ev/$1" ); }',
  '# ev_deps <name> <dir>: install the node checkout\'s dependencies; non-zero fails',
  'ev_deps() { :; }',
  '# ev_build <name> <dir>: build the node checkout; non-zero fails',
  'ev_build() { :; }',
  '# ev_smoke <name> <dir>: smoke-test the built probe checkout, e.g. collect its tests; non-zero fails',
  'ev_smoke() { :; }',
  '# ev_lint <name> <dir>: print one finding line per lint finding in the node checkout, exit non-zero if there is any',
  'ev_lint() { :; }',
  '# ev_wave_build <dir>=<sha> ...: build the merged target after the merge, <sha> being its tip before the merge; non-zero is red',
  'ev_wave_build() { :; }',
  '# ev_subject <id>: print the commit subject of node <id>',
  'ev_subject() { local t=feat; case "${1##*/}" in fix-*) t=fix ;; esac; case "$1" in */*) echo "$t(${1%%/*}): ${1##*/}" ;; *) echo "$t: $1" ;; esac; }',
]

const FUNCS = [
  'ev_pkg() { ev_worktree_paths "$1" "$2" | { read -r _ p; echo "$p"; }; }',
  'ev_fp() { local l p; while read -r l p; do echo "$l $(cd "$p" && git rev-parse "$EV_TARGET")"; done < <(ev_worktree_paths "$1" "$2") | git hash-object --stdin; }',
  'ev_sync() { local l p; while read -r l p; do ( cd "$p" || { echo "SYNC_FAIL $l missing $p"; exit 0; }; git merge-base --is-ancestor "$EV_TARGET" HEAD && exit 0; if git merge-base --is-ancestor HEAD "$EV_TARGET"; then git merge -q --ff-only "$EV_TARGET" > /dev/null 2>&1 || echo "SYNC_FAIL $l local changes overlap $EV_TARGET"; else echo "SYNC_SKIP $l has node commits"; fi ) < /dev/null; done < <(ev_worktree_paths "$1" "$2"); }',
  'ev_rows() { local l p b; while read -r l p; do ( cd "$p" 2> /dev/null && b=$(git branch --show-current) && echo "ROW $1 $l $p ${b:--} $(git rev-parse HEAD) $(git rev-parse "$EV_TARGET") $(git rev-list --count "$EV_TARGET"..HEAD) $(git status --porcelain | wc -l | tr -d " ")" || echo "ROW_MISSING $1 $l" ); done < <(ev_worktree_paths "$1" "$2"); }',
  'ev_norm() { local ps=() l p x; while read -r l p; do ps+=("$p/"); done < <(ev_worktree_paths "$1" "$2"); grep -E "$EV_LINT_RE" | while IFS= read -r x; do for p in "${ps[@]}"; do x=${x//"$p"/}; done; printf "%s\\n" "$x"; done | sed -E "s/:[0-9]+(:[0-9]+)?:/:/" | sort -u; }',
  'ev_keep() { local l p; while read -r l p; do cd "$p" 2> /dev/null || { echo "nocd $l"; return; }; [ -z "$(git status --porcelain)" ] || { echo "dirty $l"; return; }; git merge-base --is-ancestor HEAD "$EV_TARGET" || { echo "notontarget $l"; return; }; done < <(ev_worktree_paths "$1" "$2"); }',
]

const PRELUDE = [...HOOKS, `[ -f "${PLAN}/build.sh" ] && . "${PLAN}/build.sh"`, ...FUNCS]

// ---- Prompt builders, one per role ----

const COMMON = [
  'This is a one-shot step of an approved Workflow build. Your task is the one stated below; any other question or request in inherited context is not your task. Do not SendMessage anyone - your return value is your report.',
  `Rules: in every shell call use "cd <absolute path> && <command>"; never call EnterWorktree; follow the plan's Constraints in the "${FOCUS} show" output for building, testing and committing; never run git push, raise reviews, deploy or do other network writes; never sleep or wait on another agent.`,
  'If a hook says a skill is required first, load that skill with the Skill tool and rerun the same command. If a tool call is permission-denied, stop and put the denial text verbatim in "denied".',
  'Search large files and logs with grep or rg via Bash, or a bounded Read, never whole. There is no Grep or Glob tool.',
].join('\n')

const scriptPrompt = (task, file, steps, prefixes, script, repeat) => `${COMMON}

Your task: ${task}. Edit no file except ${file}.sh.
1. Write the script below verbatim to ${file}.sh with the Write tool.
2. Run these commands in order, one per shell call (timeout 600000 ms). Stop after the first one that exits non-zero or times out; never re-run one${repeat ? `, except "wait": run it again, appending with >>, while it prints a line starting with "${repeat}" (at most ${MAX_WAITS} runs)` : ''}.
${steps.map((s, i) => `   cd ${ROOT} && bash ${file}.sh${s ? ` ${s}` : ''} ${i ? '>>' : '>'} ${file}.log 2>&1`).join('\n')}
3. Read ${file}.log. Return in lines every line that starts with ${prefixes.map(p => `"${p}"`).join(' or ')}, verbatim and in order. Do not interpret, fix or retry anything.

${[...PRELUDE, ...script].join('\n')}`

// Case statement over steps: each step needs the one before it; long steps run in the background and are collected by "wait"
const steppedScript = (prefix, L, steps, isLong, arm, head = []) => {
  const S = `${L}.state`
  const state = msg => `{ echo "${prefix}_STATE ${msg}"; exit 1; }`
  return [
    ...head,
    'case "$1" in',
    ...steps.flatMap((s, i) => {
      const guard = i ? `  grep -qx ${steps[i - 1]} "${S}" || ${state(`step ${steps[i - 1]} did not finish`)}` : `  : > "${S}"`
      const done = `  echo ${s} >> "${S}"; echo "${prefix}_STEP ${s}" ;;`
      return isLong(s) ? [
        `${s})`,
        guard,
        `  echo ${s} > "${L}.step"`,
        `  nohup bash "$0" run-${s} > "${L}.out" 2>&1 < /dev/null &`,
        `  echo $! > "${L}.pid"`,
        `  echo "${prefix}_LAUNCH ${s}" ;;`,
        `run-${s})`,
        ...arm(s, state),
        done,
      ] : [`${s})`, guard, ...arm(s, state), done]
    }),
    ...(steps.some(isLong) ? [
      'wait)',
      `  [ -f "${L}.pid" ] || ${state('wait before any step was launched')}`,
      `  pid=$(cat "${L}.pid")`,
      '  waited=0',
      `  while kill -0 "$pid" 2> /dev/null && [ "$waited" -lt ${WAIT_SECONDS} ]; do sleep ${POLL_SECONDS}; waited=$((waited + ${POLL_SECONDS})); done`,
      `  step=$(cat "${L}.step")`,
      `  if kill -0 "$pid" 2> /dev/null; then echo "${prefix}_WAIT $step"; exit 0; fi`,
      `  cat "${L}.out"`,
      `  grep -qx "${prefix}_STEP $step" "${L}.out" && exit 0`,
      `  grep -Eq '^${prefix}_(FAIL|STATE) ' "${L}.out" || echo "${prefix}_STATE $step ended without a result ${L}.out"`,
      '  exit 1 ;;',
    ] : []),
    `  *) ${state('unknown step $1')} ;;`,
    'esac',
  ]
}

const scoutScript = () => [
  `mkdir -p "${LOGS}" || { echo "SCOUT_FAIL mkdir"; exit 1; }`,
  `cd "${PLAN}" || { echo "SCOUT_FAIL nocd"; exit 1; }`,
  `${FOCUS} waves "${PLAN}" > "${LOGS}/waves.txt" 2>&1 || { echo "SCOUT_FAIL waves ${LOGS}/waves.txt"; exit 1; }`,
  `awk '/^### Wave /{w=$3; next} /^- \\[/{id=$0; sub(/^- \\[.\\] /, "", id); sub(/ .*/, "", id); print w, id}' "${LOGS}/waves.txt" > "${LOGS}/ids.txt" || { echo "SCOUT_FAIL awk"; exit 1; }`,
  'while read -r w id; do',
  '  case "$id" in */*) dir="${id%%/*}"; slug="${id#*/}" ;; *) dir=.; slug="$id" ;; esac',
  '  if [ -f "$EV_PLAN/$dir/nodes/done/$slug.md" ]; then state=done; else state=todo; fi',
  `  if [ "$w" -lt ${WAVE} ]; then`,
  '    [ "$state" = done ] || continue',
  '    repo=$(ev_repo "$dir") || { echo "PRE_MISSING $id nocd"; continue; }',
  '    subject=$(ev_subject "$id")',
  '    if (cd "$repo" && git log --format=%s "$EV_TARGET" < /dev/null | grep -Fxq -- "$subject"); then echo "PRE_OK $id"; else echo "PRE_MISSING $id"; fi',
  `  elif [ "$w" -eq ${WAVE} ]; then`,
  `    if ${FOCUS} ready "${PLAN}" "$id" < /dev/null > /dev/null 2>&1; then r=ready; else r=notready; fi`,
  '    echo "NODE $id $r $state"',
  '  fi',
  `done < "${LOGS}/ids.txt"`,
  'echo "SCOUT_CPUS $(getconf _NPROCESSORS_ONLN)"',
  `echo "SCOUT_DIRS $(awk '{ d = "."; if (index($2, "/")) d = substr($2, 1, index($2, "/") - 1); print d }' "${LOGS}/ids.txt" | sort -u | tr '\\n' ' ')"`,
  `[ "$(awk '$1 > m { m = $1 } END { print m + 0 }' "${LOGS}/ids.txt")" -le ${WAVE} ] && echo SCOUT_LAST`,
  'echo SCOUT_END',
]

const scoutPrompt = () => scriptPrompt(`list the nodes of wave ${WAVE} and preflight the earlier waves (run ${STAMP})`, `${LOGS}/scout`, [''], ['NODE ', 'PRE_', 'SCOUT_'], scoutScript())

const setupScript = n => [
  `ev_worktree_add ${n.name} ${n.dir} < /dev/null || echo "SETUP_FAIL ${n.name} add"`,
  `ev_sync ${n.name} ${n.dir}`,
  `if [ -f "${nodeFile(n)}" ]; then cd "${PLAN}" && ${FOCUS} start "${PLAN}" ${n.id} < /dev/null || echo "SETUP_FAIL ${n.name} start"; fi`,
  `ev_rows ${n.name} ${n.dir}`,
]

const SETUP_MARKS = ['ROW ', 'ROW_MISSING ', 'SETUP_FAIL ', 'NO_WORKTREE ', 'SYNC_FAIL ']

const setupPrompt = n => scriptPrompt(`create the isolated git worktree for plan node ${n.id}`, `${LOGS}/setup-${n.name}`, [''], SETUP_MARKS, setupScript(n))

const resumeScript = n => [
  `[ -d "${pkgDirOf(n)}" ] || { echo "NO_WORKTREE ${n.name}"; exit 0; }`,
  `ev_sync ${n.name} ${n.dir}`,
  n.done ? `cd "${pkgDirOf(n)}" && if [ -n "$(git status --porcelain)" ]; then git add -A && git commit -q -m "$(ev_subject ${n.id})" || echo "SETUP_FAIL ${n.name} commit"; fi`
    : REBUILD.includes(n.id) ? '' : `cd "${pkgDirOf(n)}" && if [ -f "${nodeFile(n)}" ] || [ -f "${nodeFile(n, 'building')}" ]; then ${FOCUS} built "${PLAN}" ${n.id} || echo "SETUP_FAIL ${n.name} built"; fi`,
  `ev_rows ${n.name} ${n.dir}`,
].filter(Boolean)

const resumePrompt = n => scriptPrompt(`prepare the existing git worktree of plan node ${n.id} for a resumed build`, `${LOGS}/resume-${n.name}`, [''], SETUP_MARKS, resumeScript(n))

const testWriterPrompt = (n, emptyLog) => `${COMMON}

Your task: write the acceptance tests for plan node ${n.id} in ${n.pkgDir} (a git worktree). Run "cd ${n.pkgDir} && ${FOCUS} show ${PLAN} ${n.id}" once: it prints the plan, the node brief and its dependencies' outputs. Write one test per acceptance criterion and no others, where and how the brief and the package's existing tests say; reuse existing fixtures. Edit only test files in the node's Scope. Use the Edit or Write tool for every file write, never sed -i, heredocs or other shell writes. Do not write implementation code, run builds or tests, or commit. A criterion the node's test command checks without a new test (e.g. a docs-only node) needs none - say which in notes. Return the test files you wrote or changed.${emptyLog ? ` Your previous tests were not selected by the node's test command (log ${emptyLog}; search it, don't read it whole): make the command select them.` : ''}`

const testsScript = (n, attempt) => {
  const L = `${LOGS}/tests-${n.name}-${attempt}`
  return steppedScript('TESTS', L, TESTS_STEPS, isLongStep, (s, state) => ({
    files: [
      `  cd "${n.pkgDir}" || ${state(`nocd ${n.pkgDir}`)}`,
      `  if git status --porcelain < /dev/null | grep -Eq '${TEST_PATH_RE}'; then echo TESTS_OK; else echo TESTS_MISSING; exit 1; fi`,
    ],
    build: [`  ev_build ${n.name} ${n.dir} > "${L}-build.log" 2>&1 < /dev/null || ${state(`build failed ${L}-build.log`)}`],
    collect: [
      `  cd "${n.pkgDir}" || ${state(`nocd ${n.pkgDir}`)}`,
      `  if ${FOCUS} collect "${PLAN}" ${n.id} > "${L}-collect.log" 2>&1 < /dev/null; then echo TESTS_COLLECTED; else echo "TESTS_EMPTY ${L}-collect.log"; exit 1; fi`,
    ],
  })[s])
}

const testsCheckPrompt = (n, attempt) => scriptPrompt(`check that the test writer left a changed or added test file that the node's test command selects, in the worktree of plan node ${n.id} (attempt ${attempt})`, `${LOGS}/tests-${n.name}-${attempt}`, withWaits(TESTS_STEPS), ['TESTS_'], testsScript(n, attempt), 'TESTS_WAIT')

const implRules = () => 'Edit only files in the node\'s Scope. Use the Edit or Write tool for every file write, never sed -i, heredocs or other shell writes. Minimal diff in the package\'s existing style; no unrequested comments, refactors or reformatting. Run no build or test except a formatter the plan\'s Constraints name. Do not commit. If the brief lacks a fact you need or contradicts the code, stop and return status "blocked" with the gap in one sentence - do not guess. When done, return status "done" with the files you changed. Load the git-usage skill before your first git add, commit or rebase.'

const implementerPrompt = (n, tests) => `${COMMON}

Your task: implement plan node ${n.id} in ${n.pkgDir} so its acceptance tests pass. Run "cd ${n.pkgDir} && ${FOCUS} show ${PLAN} ${n.id}" once for the plan, the brief and its dependencies' outputs. The test writer wrote: ${tests.files.join(', ') || 'no new tests'}${tests.notes ? ` (${tests.notes})` : ''}. Do not change those tests unless one contradicts its criterion's text; then fix it and say so in note. ${implRules()}`

const fixerPrompt = (n, g, round) => `${COMMON}

Your task: fix plan node ${n.id} in ${n.pkgDir}; its gate failed (fix round ${round} of ${MAX_FIX_ROUNDS}). Failure: ${g.reason}. Full log: ${g.log} (search it, don't read it whole). Run "cd ${n.pkgDir} && ${FOCUS} show ${PLAN} ${n.id}" once for the plan, the brief and its dependencies' outputs. Fix the cause in code; change a test only where it contradicts its criterion's text, and say so. If the failure is "outside scope: <files>", undo this node's changes to those files rather than widen scope. ${implRules()}`

const gateScript = (n, tag, steps) => {
  const L = `${LOGS}/${n.name}-${tag}`
  const hook = (name, log) => `${name} ${n.name} ${n.dir} > "${log}" 2>&1 < /dev/null`
  const failNode = (reason, state) => n.probe ? [] : [`    ${FOCUS} fail "${PLAN}" ${n.id} '${reason}' < /dev/null || ${state('focus.py fail failed')}`]
  const failed = (reason, log) => [`    echo "GATE_FAIL ${reason} ${log}"`, `    grep -m ${MAX_DETAILS} -E '${ERR_RE}' "${log}" | sed 's/^/GATE_DETAIL /'`, '    exit 1']
  const cdPkg = state => `  cd "${pkgDirOf(n)}" || ${state('nocd')}`
  const lintBase = `${ROOT}/lint-base`
  const arm = (s, state) => ({
    add: [`  ev_worktree_add ${n.name} ${n.dir} < /dev/null || ${state('worktree add failed')}`],
    sync: [
      `  sync=$(ev_sync ${n.name} ${n.dir} | grep -m 1 SYNC_FAIL)`,
      `  [ -z "$sync" ] || ${state('$sync')}`,
    ],
    deps: [
      `  fp=$(ev_fp ${n.name} ${n.dir})`,
      `  if [ "$(cat "${ROOT}/${n.name}.deps" 2> /dev/null)" != "$fp" ]; then`,
      `    ${hook('ev_deps', `${L}-deps.log`)} || ${state(`dependencies failed ${L}-deps.log`)}`,
      `    echo "$fp" > "${ROOT}/${n.name}.deps"`,
      '  fi',
    ],
    build: [
      ...(n.probe ? [] : [`  if [ -f "${nodeFile(n)}" ] || [ -f "${nodeFile(n, 'building')}" ]; then ${FOCUS} built "${PLAN}" ${n.id} < /dev/null || ${state('focus.py built failed')}; fi`]),
      `  if ! ${hook('ev_build', `${L}-build.log`)}; then`,
      ...failNode('build failed', state),
      ...failed('build failed', `${L}-build.log`),
      '  fi',
    ],
    smoke: [
      `  if ! ${hook('ev_smoke', `${L}-smoke.log`)}; then`,
      ...failed('smoke failed', `${L}-smoke.log`),
      '  fi',
    ],
    baseline: [
      `  fp=$(ev_fp ${n.name} ${n.dir})`,
      `  mkdir -p "${lintBase}"`,
      `  if [ ! -f "${lintBase}/$fp.rc" ]; then`,
      `    ${hook('ev_lint', `${L}-lint.raw`)}`,
      '    rc=$?',
      `    ev_norm ${n.name} ${n.dir} < "${L}-lint.raw" > "${lintBase}/$fp.txt"`,
      `    echo "$rc" > "${lintBase}/$fp.rc"`,
      '  fi',
    ],
    lint: [
      `  if [ ! -f "${nodeFile(n, 'done')}" ]; then`,
      `    fp=$(ev_fp ${n.name} ${n.dir})`,
      `    [ -f "${lintBase}/$fp.rc" ] || ${state('no lint baseline for $fp')}`,
      `    ${hook('ev_lint', `${L}-lint.raw`)}`,
      '    rc=$?',
      `    ev_norm ${n.name} ${n.dir} < "${L}-lint.raw" > "${L}-lint.txt"`,
      `    comm -13 "${lintBase}/$fp.txt" "${L}-lint.txt" > "${L}-lint.new"`,
      `    if [ -s "${L}-lint.new" ]; then`,
      ...failNode('lint: new findings', state),
      `      echo "GATE_FAIL lint: new findings ${L}-lint.new"`,
      `      head -n ${MAX_DETAILS} "${L}-lint.new" | sed 's/^/GATE_DETAIL /'`,
      '      exit 1',
      '    fi',
      `    if [ "$rc" -ne 0 ] && [ "$(cat "${lintBase}/$fp.rc")" -eq 0 ]; then`,
      ...failNode('lint exited non-zero, baseline 0', state),
      `      echo "GATE_FAIL lint exited $rc, baseline 0 ${L}-lint.raw"`,
      `      grep -m ${MAX_DETAILS} -E '${ERR_RE}' "${L}-lint.raw" | sed 's/^/GATE_DETAIL /'`,
      '      exit 1',
      '    fi',
      '  fi',
    ],
    check: [
      `  if [ ! -f "${nodeFile(n, 'done')}" ]; then`,
      `  ${cdPkg(state)}`,
      `    ${FOCUS} check "${PLAN}" ${n.id} --node-only --base "$EV_TARGET" > "${L}-check.log" 2>&1 < /dev/null`,
      '    rc=$?',
      '    if [ "$rc" -ne 0 ]; then',
      `      reason=$(grep -m 1 '^fail ${n.slug}: ' "${L}-check.log")`,
      `      [ -n "$reason" ] || ${state(`focus.py check exited $rc without failing the node: ${L}-check.log`)}`,
      `      echo "GATE_FAIL $reason ${L}-check.log"`,
      `      grep -m ${MAX_DETAILS} -E '${ERR_RE}' "${L}-check.log" | sed 's/^/GATE_DETAIL /'`,
      '      exit 1',
      '    fi',
      `    [ -f "${nodeFile(n, 'done')}" ] || ${state('check exited 0 but the node is not in nodes/done')}`,
      '  fi',
    ],
    commit: [
      `  [ -f "${nodeFile(n, 'done')}" ] || ${state('the node is not in nodes/done')}`,
      cdPkg(state),
      `  [ "$(git branch --show-current)" != "$EV_TARGET" ] || ${state('worktree is on the target branch')}`,
      `  subject=$(ev_subject ${n.id})`,
      `  if [ -n "$(git status --porcelain)" ]; then git add -A && git commit -q -m "$subject" || ${state('git commit failed')}; fi`,
      `  [ "$(git log -1 --format=%s)" = "$subject" ] || ${state('HEAD is not the node commit')}`,
      '  echo "GATE_PASS $(git rev-parse HEAD)"',
    ],
  })[s]
  return steppedScript('GATE', L, steps, isLongStep, arm, [`[ "$1" = ${steps[0]} ] && [ "$(uname)" = Darwin ] && echo "GATE_IDLE $(iostat -c 2 -w 1 | awk 'END{print $6}')"`])
}

const gatePrompt = (n, attempt) => scriptPrompt(`gate plan node ${n.id} (attempt ${attempt})`, `${LOGS}/gate-${n.name}-${attempt}`, withWaits(GATE_STEPS), ['GATE_'], gateScript(n, attempt, GATE_STEPS), 'GATE_WAIT')

const probePrompt = p => scriptPrompt(`prove the toolchain builds and smoke-tests, and record the lint baseline, in the persistent probe worktree of plan dir ${p.dir}`, `${LOGS}/probe-${p.name}`, withWaits(PROBE_STEPS), ['GATE_'], gateScript({ ...p, probe: true }, 'probe', PROBE_STEPS), 'GATE_WAIT')

const mergeBase = d => `${LOGS}/merge-base-${d}`

const mergeScript = (passed, byId, touched, tag) => {
  const L = `${LOGS}/merge-${tag}`
  const J = `${LOGS}/join.txt`
  const joinArm = state => [
    `  if [ ! -f "${J}" ]; then`,
    `    cd "${PLAN}" || ${state(`nocd ${PLAN}`)}`,
    `    ${FOCUS} join "${PLAN}" > "${J}.tmp" 2>&1 < /dev/null || ${state(`focus.py join failed ${J}.tmp`)}`,
    `    mv "${J}.tmp" "${J}" || ${state(`mv ${J}.tmp failed`)}`,
    '  fi',
    `  if [ "$(cat "${J}")" != 'nothing to join' ]; then sed 's/^/MERGE_JOIN /' "${J}"; exit 1; fi`,
  ]
  const nodeArm = (r, state) => {
    const n = byId[r.id]
    const log = `${L}-${n.name}`
    return [
      `  if git merge-base --is-ancestor "${r.branch}" "$EV_TARGET" < /dev/null; then`,
      `    echo "MERGED ${n.id} $(git rev-parse "${r.branch}")"`,
      '  else',
      `    cd "${n.pkgDir}" || ${state(`nocd ${n.pkgDir}`)}`,
      `    [ "$(git branch --show-current)" = "${r.branch}" ] || ${state(`${n.id} worktree not on ${r.branch}`)}`,
      `    [ ! -e "$(git rev-parse --git-path rebase-merge)" ] && [ ! -e "$(git rev-parse --git-path rebase-apply)" ] || ${state(`${n.id} rebase already in progress in ${n.pkgDir}`)}`,
      `    st=$(git status --porcelain) || ${state(`${n.id} git status failed`)}`,
      `    [ -z "$st" ] || ${state(`${n.id} worktree not clean`)}`,
      `    if git rebase "$EV_TARGET" > "${log}-rebase.log" 2>&1 < /dev/null; then`,
      `      cd "$repo" || ${state('nocd $repo')}`,
      `      git merge --ff-only "${r.branch}" > "${log}-ff.log" 2>&1 < /dev/null || ${state(`${n.id} fast-forward failed ${log}-ff.log`)}`,
      `      echo "MERGED ${n.id} $(git rev-parse HEAD)"`,
      '    else',
      `      files=$(git diff --name-only --diff-filter=U | tr '\\n' ' ')`,
      `      git rebase --abort > /dev/null 2>&1 < /dev/null || ${state(`${n.id} rebase --abort failed in ${n.pkgDir}`)}`,
      `      [ -n "$files" ] || ${state(`${n.id} rebase failed without conflicts ${log}-rebase.log`)}`,
      `      echo "MERGE_CONFLICT ${n.id} $files"`,
      `      cd "$repo" || ${state('nocd $repo')}`,
      '    fi',
      '  fi',
    ]
  }
  const pkgArm = (d, state) => [
    `  repo=$(ev_repo ${d}) || ${state(`no repo for ${d}`)}`,
    `  cd "$repo" || ${state('nocd $repo')}`,
    '  echo "MERGE_TARGET $EV_TARGET"',
    `  [ "$(git branch --show-current)" = "$EV_TARGET" ] || ${state(`${d} repo not on $EV_TARGET`)}`,
    `  st=$(git status --porcelain) || ${state(`${d} git status failed`)}`,
    `  [ -z "$st" ] || ${state(`${d} repo not clean`)}`,
    `  [ -f "${mergeBase(d)}" ] || git rev-parse "$EV_TARGET" > "${mergeBase(d)}" || ${state(`${d} base not recorded`)}`,
    ...passed.filter(r => byId[r.id].dir === d).flatMap(r => nodeArm(r, state)),
  ]
  return steppedScript('MERGE', L, mergeSteps(touched), () => false, (s, state) => s === 'join' ? joinArm(state) : pkgArm(s.slice(4), state))
}

const mergeSteps = touched => ['join', ...touched.map(d => `pkg-${d}`)]

const resolvePrompt = (n, branch, files, target) => `${COMMON}

Your task: rebase branch ${branch} of plan node ${n.id} onto ${target} in ${n.pkgDir}, resolving its conflicts only where safe. A scripted rebase stopped on conflicts in: ${files.join(', ')}. Work only in ${n.pkgDir}: never cd to or change the main checkout of the repo, never merge, never commit except through the rebase.
1. Run: cd ${n.pkgDir} && git rebase ${target} < /dev/null   (if git says a rebase is already in progress, go to step 2)
2. For each file listed by "cd ${n.pkgDir} && git diff --name-only --diff-filter=U": if every conflict hunk is either two independent additions (keep both sides, the HEAD (${target}) side first) or both sides adding names to the same import statement (keep the union of names), resolve it using the Edit tool (never sed -i, heredocs or other shell writes), then git add that file. If any hunk is anything else, run "cd ${n.pkgDir} && git rebase --abort" and return status "skipped" with those files and one sentence why in note.
3. Run: cd ${n.pkgDir} && GIT_EDITOR=true git rebase --continue < /dev/null   - if it stops on a new conflict, repeat step 2.
4. When the rebase finishes, check "cd ${n.pkgDir} && git status --porcelain" prints nothing, and return status "resolved" with the files you edited.
Never use --ours, --theirs, -X, --skip, reset, or checkout of a file.`

const checkSteps = touched => ['wave-build', ...touched.map(d => `cw-${d}`)]

const checksScript = (touched, tag) => {
  const state = msg => `{ echo "CHECK_STATE ${msg}"; exit 1; }`
  const arm = (s, dir, cwd, cmd, log) => [
    `${s})`,
    `  cd "${cwd}" || ${state(`nocd ${cwd}`)}`,
    `  ${cmd} > "${log}" 2>&1 < /dev/null`,
    '  rc=$?',
    `  if [ "$rc" -eq 0 ]; then echo "CHECK_OK ${dir} ${log}"; else echo "CHECK_FAIL ${dir} ${log}"; grep -m ${MAX_DETAILS} -E '${ERR_RE}| exited [0-9]+$' "${log}" | sed 's/^/CHECK_DETAIL ${dir} /'; fi`,
    `  echo "CHECK_STEP ${s}" ;;`,
  ]
  return [
    'case "$1" in',
    ...arm('wave-build', 'workspace', ROOT, `ev_wave_build ${touched.map(d => `${d}="$(cat "${mergeBase(d)}")"`).join(' ')}`, `${LOGS}/wave-build.log`),
    ...touched.flatMap(d => arm(`cw-${d}`, d, `$(ev_repo ${d})`, `${FOCUS} check-wave "${PLAN}/${d}"`, `${LOGS}/check-wave-${d.replace('.', 'root')}.log`)),
    `  *) ${state('unknown step $1')} ;;`,
    'esac',
  ]
}

const cleanupScript = ns => [
  'case "$1" in',
  ...ns.flatMap(n => [
    `${n.name})`,
    `  keep=$(ev_keep ${n.name} ${n.dir})`,
    `  if [ -n "$keep" ]; then echo "KEEP ${n.name} $keep"; else`,
    `    echo "REMOVE ${n.name}"`,
    `    ev_worktree_remove ${n.name} ${n.dir} > "${LOGS}/remove-${n.name}.log" 2>&1 < /dev/null || echo "REMOVE_FAIL ${n.name} ${LOGS}/remove-${n.name}.log"`,
    '  fi',
    `  echo "CLEANUP_STEP ${n.name}" ;;`,
  ]),
  '  *) echo "CLEANUP_STATE unknown step $1"; exit 1 ;;',
  'esac',
]

const cleanupPrompt = (ns, tag, what) => scriptPrompt(`remove the ${what} where safe`, `${LOGS}/cleanup-${tag}`, ns.map(n => n.name), ['REMOVE', 'KEEP ', 'CLEANUP_'], cleanupScript(ns))

const triagePrompt = (red, mergedIds, unmerged) => `${COMMON}

Your task: classify each failure in these wave-${WAVE} checks. Read-only: do not edit files or run builds or tests.
${red.map(c => `- ${c.dir}: log ${c.log}; reported: ${c.failures.join(' | ')}`).join('\n')}
Merged in wave ${WAVE}: ${mergedIds.join(', ')}. Not merged: ${unmerged.join(', ') || 'none'}.
Use "${FOCUS} waves ${PLAN}" and "${FOCUS} show ${PLAN} <node>" for the plan, and the merged code on the target branch of each touched repo. Classify every failing test or error:
- unbuilt: caused by a node of this wave that was not merged; name it in node.
- regression: caused by merged code of this wave; name the node and give the exact fix as file:line plus the change.
- plan-defect: the failing site (the test, or the file and symbol of a lint, format, type, import or build error) is in the Scope of a node in a later wave, or the plan misses it; name the later node in laterNode and quote its Scope entry in fix.`

// ---- Control flow ----

const fail = (n, status, reason, log = '') => ({ ok: false, id: n.id, status, reason, log })
const stopReason = (r, who) => !r ? `${who} returned nothing` : r.denied ? `denied: ${r.denied}` : `${who} blocked: ${r.note}`

const call = async (prompt, opts) => (await agent(prompt, opts)) || agent(prompt, { ...opts, label: `${opts.label}:retry` })
const marks = (r, tag) => r.lines.filter(l => l.startsWith(`${tag} `)).map(l => l.slice(tag.length + 1))
const gateMarks = r => {
  const m = (marks(r, 'GATE_FAIL')[0] || '').match(/^(.*) (\/\S+)$/)
  return {
    state: marks(r, 'GATE_STATE')[0],
    fail: m && { reason: [m[1], ...marks(r, 'GATE_DETAIL')].join(' | '), log: m[2] },
    pass: marks(r, 'GATE_PASS').find(sha => /^[0-9a-f]{40}$/.test(sha)),
    steps: marks(r, 'GATE_STEP'),
  }
}

const mergeMarks = r => ({
  state: marks(r, 'MERGE_STATE')[0],
  target: marks(r, 'MERGE_TARGET')[0],
  join: marks(r, 'MERGE_JOIN'),
  steps: marks(r, 'MERGE_STEP'),
  merged: marks(r, 'MERGED').map(l => l.split(' ')).filter(([, sha]) => /^[0-9a-f]{40}$/.test(sha)).map(([id, sha]) => ({ id, sha })),
  conflicts: marks(r, 'MERGE_CONFLICT').map(l => l.trim().split(' ')).map(([id, ...files]) => ({ id, files })),
})

const mergePass = async (passed, byId, touched, tag) => {
  const steps = mergeSteps(touched)
  const r = await call(scriptPrompt(`merge wave ${WAVE}'s passed nodes onto the target branch (pass ${tag})`, `${LOGS}/merge-${tag}`, steps, ['MERGE'], mergeScript(passed, byId, touched, tag)), { label: `merge${tag}:wave-${WAVE}`, phase: 'Merge', agentType: RUNNER, schema: MARKERS })
  if (!r || r.denied) return { merged: [], conflicts: [], stopped: r ? `denied: ${r.denied}` : 'merge returned nothing' }
  const m = mergeMarks(r)
  const unreported = passed.map(p => p.id).filter(id => ![...m.merged, ...m.conflicts].some(x => x.id === id))
  const stopped = m.state ? `merge state: ${m.state}`
    : m.join.length ? `focus.py join changed the plan: ${m.join.join(' | ')}`
    : !m.steps.includes(steps.at(-1)) ? `merge script did not finish (steps done: ${m.steps.join(', ') || 'none'})`
    : unreported.length ? `merge reported no MERGED or MERGE_CONFLICT for: ${unreported.join(', ')}` : ''
  return { ...m, stopped }
}

const runChecks = async touched => {
  const dirs = ['workspace', ...touched]
  const r = await call(scriptPrompt(`run wave ${WAVE}'s wave build and check-wave per touched plan dir`, `${LOGS}/checks`, checkSteps(touched), ['CHECK_'], checksScript(touched)), { label: `checks:wave-${WAVE}`, phase: 'Merge', agentType: RUNNER, schema: MARKERS })
  if (!r || r.denied) return { checks: [], problem: r ? `denied: ${r.denied}` : 'checks returned nothing' }
  const line = (tag, dir) => marks(r, tag).find(l => l.startsWith(`${dir} `))
  const checks = dirs.flatMap(dir => {
    const hit = line('CHECK_OK', dir) || line('CHECK_FAIL', dir)
    return hit ? [{ dir, ok: !!line('CHECK_OK', dir), log: hit.slice(dir.length + 1), failures: marks(r, 'CHECK_DETAIL').filter(l => l.startsWith(`${dir} `)).map(l => l.slice(dir.length + 1)) }] : []
  })
  const missing = dirs.filter(dir => !checks.some(c => c.dir === dir))
  const state = marks(r, 'CHECK_STATE')[0]
  return { checks, problem: state ? `checks state: ${state}` : missing.length ? `checks did not run for: ${missing.join(', ')}` : '' }
}

const setupRows = r => r && {
  rows: r.lines.filter(l => l.startsWith('ROW ')).map(l => {
    const [, , label, path, branch, head, target, ahead, dirty] = l.split(' ')
    return { label, path, branch, head, target, ahead: Number(ahead), dirty: Number(dirty) }
  }),
  failures: r.lines.filter(l => !l.startsWith('ROW ')),
  denied: r.denied,
}

const checkSetup = (n, r) => {
  if (!r || r.denied) return fail(n, 'escalate', r ? `denied: ${r.denied}` : 'setup returned nothing')
  const problems = [...r.failures]
  if (!r.rows.length) problems.push('no checkout rows')
  for (const row of r.rows) if (row.branch === '-' || row.head !== row.target) problems.push(`${row.label} not a fresh branch at the target (${row.branch} ${row.head} vs ${row.target})`)
  if (problems.length) return { ...fail(n, 'escalate', `setup: ${problems.join('; ')}`), rows: r.rows }
  n.pkgDir = r.rows[0].path
  return { ok: true, id: n.id, branch: r.rows[0].branch, rows: r.rows }
}

const checkResume = (n, r) => {
  if (!r || r.denied) return fail(n, 'escalate', r ? `denied: ${r.denied}` : 'resume setup returned nothing')
  if (r.failures.some(f => f.startsWith('NO_WORKTREE'))) return n.done ? { ok: false, id: n.id, status: 'gone' } : fail(n, 'escalate', 'resume: worktree missing')
  const problems = [...r.failures]
  const [row] = r.rows
  if (!row) problems.push('checkout rows missing')
  else if (row.branch === '-') problems.push('worktree not on a node branch')
  else if (n.done && (row.ahead < 1 || row.dirty > 0)) problems.push(`done but ${row.dirty > 0 ? 'still dirty' : 'no commit on branch'}`)
  if (problems.length) return { ...fail(n, 'escalate', `resume: ${problems.join('; ')}`), rows: r.rows }
  n.pkgDir = row.path
  return { ok: true, id: n.id, branch: row.branch, rows: r.rows }
}

const runSetup = (n, prompt, label, check) => call(prompt, { label: `${label}:${n.id}`, phase: 'Setup', agentType: RUNNER, schema: MARKERS }).then(r => check(n, setupRows(r)))
const setupNode = n => runSetup(n, setupPrompt(n), 'setup', checkSetup)
const resumeNode = n => runSetup(n, resumePrompt(n), 'resume', checkResume)
const build = (s, n) => s.ok && s.status !== 'passed' && (!RESUME || REBUILD.includes(n.id))

const writeTests = async (n, s) => {
  let emptyLog = ''
  let last = 'left no changed or added test file in the worktree'
  for (let attempt = 1; attempt <= MAX_TEST_ATTEMPTS; attempt++) {
    const t = await call(testWriterPrompt(n, emptyLog), { label: `tests${attempt}:${n.id}`, phase: 'Build', agentType: 'worker-sonnet-medium', schema: TESTS })
    if (!t || t.denied) return fail(n, 'escalate', t ? `denied: ${t.denied}` : 'test writer returned nothing')
    if (!t.files.length && t.notes) return { ...s, tests: t }
    const c = await withBuildSlot(() => call(testsCheckPrompt(n, attempt), { label: `testscheck${attempt}:${n.id}`, phase: 'Build', agentType: RUNNER, schema: MARKERS }))
    if (!c || c.denied) return fail(n, 'escalate', c ? `denied: ${c.denied}` : 'tests check returned nothing')
    const state = marks(c, 'TESTS_STATE')[0]
    if (state) return fail(n, 'escalate', `tests check state: ${state}`)
    if (c.lines.includes('TESTS_COLLECTED')) return { ...s, tests: t }
    emptyLog = marks(c, 'TESTS_EMPTY')[0] || ''
    if (emptyLog) last = `wrote tests the node's test command does not select (log ${emptyLog})`
    else if (c.lines.includes('TESTS_MISSING')) last = 'left no changed or added test file in the worktree'
    else return fail(n, 'escalate', `tests check printed no TESTS_COLLECTED, TESTS_EMPTY or TESTS_MISSING: ${c.lines.join(' | ') || 'no markers'}`)
  }
  return fail(n, 'escalate', `test writer ${last} after ${MAX_TEST_ATTEMPTS} attempts`)
}

const implement = async (n, s) => {
  const f = await call(implementerPrompt(n, s.tests), { label: `impl:${n.id}`, phase: 'Build', agentType: 'worker-sonnet-high', schema: IMPL })
  if (!f || f.denied || f.status !== 'done') return fail(n, 'escalate', stopReason(f, 'implementer'))
  return s
}

const gateLoop = async (n, s) => {
  let last = null
  for (let round = 0; round <= MAX_FIX_ROUNDS; round++) {
    const r = await withBuildSlot(() => call(gatePrompt(n, round + 1), { label: `gate${round + 1}:${n.id}`, phase: 'Gate', agentType: RUNNER, schema: MARKERS }))
    if (!r || r.denied) return fail(n, 'escalate', r ? `denied: ${r.denied}` : 'gate returned nothing')
    const g = gateMarks(r)
    if (g.state) return fail(n, 'escalate', `gate state: ${g.state}`)
    if (!g.fail) return g.pass ? { ok: true, id: n.id, status: 'passed', commit: g.pass, branch: s.branch } : fail(n, 'escalate', `gate printed no GATE_PASS, GATE_FAIL or GATE_STATE (steps done: ${g.steps.join(', ') || 'none'})`)
    last = g.fail
    if (round === MAX_FIX_ROUNDS) break
    const f = await call(fixerPrompt(n, g.fail, round + 1), { label: `fix${round + 1}:${n.id}`, phase: 'Build', agentType: 'worker-sonnet-high', schema: IMPL })
    if (!f || f.denied || f.status !== 'done') return fail(n, 'escalate', stopReason(f, 'fixer'), g.fail.log)
  }
  return fail(n, 'failed', `gate still failing after ${MAX_FIX_ROUNDS} fix rounds: ${last.reason}`, last.log)
}

phase('Scout')
const scout = await call(scoutPrompt(), { label: `scout:wave-${WAVE}`, phase: 'Scout', agentType: RUNNER, schema: MARKERS })
const stop = (what, reason) => ({ wave: WAVE, escalations: [{ what, reason }], nextWaveSafe: false })
if (!scout || scout.denied) return stop('scout', scout ? `denied: ${scout.denied}` : 'scout returned nothing')
if (!scout.lines.includes('SCOUT_END')) return stop('scout', `scout script did not finish: ${marks(scout, 'SCOUT_FAIL').join('; ') || 'no SCOUT_END'}`)
const missing = marks(scout, 'PRE_MISSING')
if (missing.length) return stop('preflight', `done nodes of earlier waves without their commit on the target branch: ${missing.join(', ')}`)
const nodeLines = marks(scout, 'NODE')
const parsed = nodeLines.map(l => l.match(/^(\S+) (ready|notready) (done|todo)$/))
const scoutNodes = parsed.filter(Boolean).map(m => ({ id: m[1], ready: m[2] === 'ready', done: m[3] === 'done' }))
const badIds = [...nodeLines.filter((_, i) => !parsed[i]), ...scoutNodes.filter(x => !NODE_RE.test(x.id)).map(x => x.id)]
if (!scoutNodes.length || badIds.length) return stop('scout', badIds.length ? `unrecognised NODE lines: ${badIds.join(', ')}` : `no wave ${WAVE}`)
const keep = x => RESUME ? x.done || x.ready : !x.done && x.ready
const skipped = scoutNodes.filter(x => !keep(x))
if (skipped.length) log(`skipping: ${skipped.map(x => `${x.id} (${x.done ? 'done' : 'not ready'})`).join(', ')}`)
const notReady = skipped.filter(x => !x.done).map(x => x.id)
const nodes = scoutNodes.filter(keep).map(x => ({ ...makeNode(x.id), done: x.done }))
if (!nodes.length) return { wave: WAVE, passed: [], notReady, escalations: notReady.length ? [{ what: 'wave', reason: `no ready nodes; not ready: ${notReady.join(', ')}` }] : [], nextWaveSafe: !notReady.length }
log(`wave ${WAVE}: ${nodes.length} node(s)`)

const cpus = Number(marks(scout, 'SCOUT_CPUS')[0])
const buildCapMax = cpus ? Math.max(1, Math.floor(cpus / 2)) : DEFAULT_BUILD_CAP
let buildCap = cpus ? Math.max(1, Math.floor(cpus / 3)) : DEFAULT_BUILD_CAP
let building = 0
const buildWaiters = []
const wakeBuilds = () => { while (building < buildCap && buildWaiters.length) { building++; buildWaiters.shift()() } }
const adaptBuildCap = r => {
  const idle = marks(r, 'GATE_IDLE').at(-1)
  const next = nextBuildCap(idle, buildCap, buildCapMax)
  if (next === buildCap) return
  log(`build cap ${buildCap} -> ${next} (idle ${idle})`)
  buildCap = next
  wakeBuilds()
}
const withBuildSlot = async run => {
  if (building < buildCap && !buildWaiters.length) building++
  else await new Promise(resolve => buildWaiters.push(resolve))
  try {
    const r = await run()
    if (r) adaptBuildCap(r)
    return r
  } finally { building--; wakeBuilds() }
}

const probeFailure = async p => {
  const r = await withBuildSlot(() => call(probePrompt(p), { label: `probe:${p.dir}`, phase: 'Setup', agentType: RUNNER, schema: MARKERS }))
  if (!r || r.denied) return r ? `denied: ${r.denied}` : 'probe returned nothing'
  const g = gateMarks(r)
  return g.state || (g.fail ? `${g.fail.reason} (log ${g.fail.log})` : g.steps.includes(PROBE_STEPS.at(-1)) ? '' : 'probe did not finish')
}

const probeReport = await Promise.all([...new Set(nodes.map(n => n.dir))].map(async dir => {
  const p = probeOf(dir)
  const reason = await probeFailure(p)
  log(reason ? `probe failed: ${p.name}: ${reason}` : `probe ok: ${p.name}`)
  return { dir, worktree: p.name, ok: !reason, reason }
}))
if (PROBE_ONLY) return { wave: WAVE, probeOnly: true, probes: probeReport, ok: probeReport.every(p => p.ok) }
const probeReasons = Object.fromEntries(probeReport.filter(p => !p.ok).map(p => [p.dir, p.reason]))

const buildNode = async (s, n) => {
  const tested = build(s, n) ? await writeTests(n, s) : s
  const implemented = build(tested, n) ? await implement(n, tested) : tested
  return implemented.ok && implemented.status !== 'passed' ? gateLoop(n, implemented) : implemented
}

const results = (await pipeline(nodes,
  n => probeReasons[n.dir] ? fail(n, 'escalate', `feasibility probe failed for ${n.dir}: ${probeReasons[n.dir]}`) : RESUME ? resumeNode(n) : setupNode(n),
  (s, n) => s.ok && s.status !== 'passed' ? buildNode(s, n) : s,
)).map((r, i) => r || fail(nodes[i], 'escalate', 'a stage threw'))

const escalations = results.filter(r => r.status !== 'passed' && r.status !== 'gone').map(r => ({ what: r.id, reason: r.reason, log: r.log }))
const passed = results.filter(r => r.status === 'passed')
log(`${passed.length}/${nodes.length} node(s) passed their gate`)
if (!passed.length) return { wave: WAVE, passed: [], notReady, escalations, nextWaveSafe: false }

phase('Merge')
const byId = Object.fromEntries(nodes.map(n => [n.id, n]))
const touched = [...new Set(passed.map(r => byId[r.id].dir))].sort()
let pass = 1
let merge = await mergePass(passed, byId, touched, pass)
const resolverNotes = {}
for (const c of merge.stopped ? [] : merge.conflicts) {
  const f = await call(resolvePrompt(byId[c.id], passed.find(r => r.id === c.id).branch, c.files, merge.target), { label: `resolve:${c.id}`, phase: 'Merge', agentType: 'worker-sonnet-medium', schema: RESOLVE })
  if (!f || f.denied) { merge = { ...merge, stopped: `conflict resolver for ${c.id}: ${f ? `denied: ${f.denied}` : 'returned nothing'}` }; break }
  resolverNotes[c.id] = f.note
  merge = await mergePass(passed, byId, touched, ++pass)
  if (merge.stopped) break
}
if (merge.stopped) {
  escalations.push({ what: 'merge', reason: merge.stopped })
  return { wave: WAVE, passed: merge.merged.map(m => m.id), notReady, escalations, nextWaveSafe: false }
}
merge.conflicts.forEach(c => escalations.push({ what: c.id, reason: `rebase conflict in ${c.files.join(', ')}${resolverNotes[c.id] ? `: ${resolverNotes[c.id]}` : ''}` }))
const mergedIds = merge.merged.map(m => m.id)
const unmerged = results.filter(r => r.status !== 'gone').map(r => r.id).filter(id => !mergedIds.includes(id))
const checkRun = await runChecks(touched)
if (checkRun.problem) escalations.push({ what: 'checks', reason: checkRun.problem })
const red = checkRun.checks.filter(c => !c.ok)
log(`merged ${mergedIds.length}; red checks: ${red.map(c => c.dir).join(', ') || 'none'}`)
const mergedNodes = mergedIds.map(id => byId[id])
const escalatedNodes = results.filter(r => r.status !== 'passed' && r.status !== 'gone').map(r => byId[r.id])
const cleanNodes = [...mergedNodes, ...escalatedNodes]
const cleanup = cleanNodes.length ? await call(cleanupPrompt(cleanNodes, 'nodes', 'node worktrees of this wave'), { label: `cleanup:wave-${WAVE}`, phase: 'Merge', agentType: RUNNER, schema: MARKERS }) : { lines: [] }
const uncleaned = cleanup ? cleanNodes.filter(n => !marks(cleanup, 'CLEANUP_STEP').includes(n.name)).map(n => n.name) : []
if (!cleanup || cleanup.denied || uncleaned.length) escalations.push({ what: 'cleanup', reason: !cleanup ? 'cleanup returned nothing' : cleanup.denied ? `denied: ${cleanup.denied}` : `cleanup script did not finish for: ${uncleaned.join(', ')}` })
else [...marks(cleanup, 'KEEP').filter(k => mergedNodes.some(n => n.name === k.split(' ')[0])), ...marks(cleanup, 'REMOVE_FAIL')].forEach(k => escalations.push({ what: 'cleanup', reason: `worktree kept: ${k}` }))
const removeFailed = cleanup ? marks(cleanup, 'REMOVE_FAIL').map(l => l.split(' ')[0]) : []
const removed = cleanup ? marks(cleanup, 'REMOVE').filter(name => !removeFailed.includes(name)) : []

phase('Triage')
if (red.length) {
  const verdict = await call(triagePrompt(red, mergedIds, unmerged), { label: `triage:wave-${WAVE}`, phase: 'Triage', agentType: 'reasoner-opus-high', schema: TRIAGE })
  if (!verdict || verdict.denied) escalations.push({ what: 'triage', reason: verdict ? `denied: ${verdict.denied}` : 'triage returned nothing' })
  else verdict.failures.filter(f => f.kind !== 'unbuilt').forEach(f => escalations.push({ what: f.node || f.laterNode || f.dir, reason: `${f.kind} in ${f.dir} ${f.test}: ${f.fix}` }))
}

if (!escalations.length && !notReady.length && scout.lines.includes('SCOUT_LAST')) {
  const probes = (marks(scout, 'SCOUT_DIRS')[0] || '').split(' ').filter(Boolean).map(probeOf)
  const probeCleanup = await call(cleanupPrompt(probes, 'probes', 'probe worktrees'), { label: `cleanup-probes:wave-${WAVE}`, phase: 'Triage', agentType: RUNNER, schema: MARKERS })
  if (!probeCleanup || probeCleanup.denied) escalations.push({ what: 'cleanup', reason: !probeCleanup ? 'probe cleanup returned nothing' : `denied: ${probeCleanup.denied}` })
  else marks(probeCleanup, 'REMOVE_FAIL').forEach(k => escalations.push({ what: 'cleanup', reason: `probe worktree kept: ${k}` }))
}

log(`wave ${WAVE}: ${escalations.length} escalation(s)`)
return { wave: WAVE, passed: mergedIds, notMerged: unmerged, notReady, checks: checkRun.checks, removedWorktrees: removed, escalations, nextWaveSafe: escalations.length === 0 && notReady.length === 0 }
