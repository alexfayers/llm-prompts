const test = require('node:test');
const assert = require('node:assert/strict');
const { readPins, findProblems } = require('./check-pi-pins.js');

const PI_PACKAGE = '@earendil-works/pi-coding-agent';

const pins = readPins({
  packages: [
    `npm:${PI_PACKAGE}@1.0.0`,
    'npm:pi-one@2.0.0',
    { source: 'npm:@scope/pi-two@3.0.0', extensions: [] },
    'git:example/ignored',
  ],
});

function command(source) {
  return { sourceInfo: { origin: 'package', source } };
}

const healthy = {
  pins,
  piVersion: '1.0.0',
  installed: new Map([
    ['pi-one', '2.0.0'],
    ['@scope/pi-two', '3.0.0'],
  ]),
  commands: [command('npm:pi-one@2.0.0')],
};

test('reads scoped and object npm pins only', () => {
  assert.deepEqual([...pins], [[PI_PACKAGE, '1.0.0'], ['pi-one', '2.0.0'], ['@scope/pi-two', '3.0.0']]);
});

test('accepts packages that match their pins', () => {
  assert.deepEqual(findProblems(healthy), []);
});

test('reports a version other than the pin', () => {
  const installed = new Map(healthy.installed).set('pi-one', '2.0.1');
  assert.match(findProblems({ ...healthy, installed })[0], /pi-one is pinned to 2\.0\.0 but 2\.0\.1/);
});

test('reports a loaded package that is not pinned', () => {
  const commands = [command('npm:pi-one@1.9.0')];
  assert.match(findProblems({ ...healthy, commands })[0], /npm:pi-one@1\.9\.0 loaded but is not pinned/);
});
