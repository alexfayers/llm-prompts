const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SETTINGS = path.join(__dirname, '../../src/llm_prompts/prompts/pi/settings.json');
const PI_PACKAGE = '@earendil-works/pi-coding-agent';
const NPM_PREFIX = 'npm:';
const RPC_TIMEOUT_MS = 120000;
const INSTALL_TIMEOUT_MS = 600000;
const PI_ENV_PREFIXES = ['PI_', 'HERDR_'];

function readPins(settings) {
  return new Map(
    settings.packages
      .map((entry) => (typeof entry === 'string' ? entry : entry.source))
      .filter((source) => source.startsWith(NPM_PREFIX))
      .map((source) => {
        const at = source.lastIndexOf('@');
        return [source.slice(NPM_PREFIX.length, at), source.slice(at + 1)];
      }),
  );
}

function findProblems({ pins, piVersion, installed, commands }) {
  const problems = [];
  for (const [name, version] of pins) {
    const actual = name === PI_PACKAGE ? piVersion : installed.get(name);
    if (actual !== version) {
      problems.push(`${name} is pinned to ${version} but ${actual ?? 'not installed'} is installed`);
    }
  }
  const pinned = new Set([...pins].map(([name, version]) => `${NPM_PREFIX}${name}@${version}`));
  const loaded = commands.filter((command) => command.sourceInfo.origin === 'package');
  for (const source of new Set(loaded.map((command) => command.sourceInfo.source))) {
    if (!pinned.has(source)) {
      problems.push(`${source} loaded but is not pinned`);
    }
  }
  return problems;
}

function run(command, args, { silentStderr = false, ...options } = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', timeout: INSTALL_TIMEOUT_MS, ...options });
  if (result.status !== 0 || (silentStderr && result.stderr.trim())) {
    throw new Error(`${command} ${args.join(' ')} failed:\n${result.stdout ?? ''}${result.stderr ?? ''}`);
  }
  return result.stdout;
}

function main() {
  const pins = readPins(JSON.parse(fs.readFileSync(SETTINGS, 'utf8')));
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-pins-'));
  const home = path.join(scratch, 'home');
  const agentDir = path.join(home, '.pi', 'agent');
  const piBin = path.join(scratch, 'pi', 'node_modules', '.bin');
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([key]) => !PI_ENV_PREFIXES.some((prefix) => key.startsWith(prefix))),
  );
  const piEnv = { ...env, HOME: home, PATH: `${piBin}${path.delimiter}${env.PATH}` };
  fs.mkdirSync(home);
  try {
    run('npm', ['install', '--prefix', path.join(scratch, 'pi'), `${PI_PACKAGE}@${pins.get(PI_PACKAGE)}`], { env: piEnv });
    run('llm-prompts', ['install', 'pi', '--root', home, '--no-update'], { env: piEnv, stdio: 'inherit' });
    const piVersion = run('pi', ['--version'], { env: piEnv }).trim();
    const rpcEnv = {
      ...piEnv,
      PI_CODING_AGENT_DIR: agentDir,
      PI_OFFLINE: '1',
      PI_SKIP_VERSION_CHECK: '1',
      PI_TELEMETRY: '0',
    };
    const output = run('pi', ['--mode', 'rpc', '--no-session'], {
      env: rpcEnv,
      cwd: home,
      silentStderr: true,
      input: '{"id":"commands","type":"get_commands"}\n',
      timeout: RPC_TIMEOUT_MS,
    });
    const reply = output
      .split('\n')
      .filter(Boolean)
      .map((line) => JSON.parse(line))
      .find((record) => record.type === 'response' && record.id === 'commands');
    if (!reply?.success) {
      throw new Error(`get_commands failed: ${JSON.stringify(reply)}`);
    }
    const installed = new Map(
      [...pins.keys()].map((name) => {
        const manifest = path.join(agentDir, 'npm', 'node_modules', name, 'package.json');
        return [name, fs.existsSync(manifest) ? JSON.parse(fs.readFileSync(manifest, 'utf8')).version : undefined];
      }),
    );
    const problems = findProblems({ pins, piVersion, installed, commands: reply.data.commands });
    if (problems.length > 0) {
      throw new Error(problems.join('\n'));
    }
    console.log(`All ${pins.size} pinned pi packages are installed and load at their pinned versions.`);
  } finally {
    fs.rmSync(scratch, { recursive: true, force: true });
  }
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}

module.exports = { readPins, findProblems };
