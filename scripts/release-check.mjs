import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const read = name => readFileSync(path.join(root, name), 'utf8');
const packageJson = JSON.parse(read('package.json'));
const manifest = JSON.parse(read('ez-plugin.json'));
const semver = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const requirementName = /^([A-Za-z0-9][A-Za-z0-9_.-]*)/;
const frozenRequirement = /^([A-Za-z0-9][A-Za-z0-9_.-]*)==\d+(?:\.\d+){1,3}$/;

assert.equal(packageJson.name, '@jc_stack/ez-fast-browser');
assert.match(packageJson.version, semver, 'package version must be exact SemVer');
assert.equal(packageJson.version, manifest.version, 'package and Ez manifest versions differ');
assert.equal(packageJson.private, true, 'Fast Browser must remain a private/local package');
assert.equal(packageJson.packageManager, 'pnpm@10.30.3', 'package-manager pin is missing');
assert.equal(packageJson.engines?.node, '>=22', 'Node support must be explicit');
assert.equal(manifest.id, 'fast-browser');

const entries = name => read(name)
  .split(/\r?\n/)
  .map(line => line.trim())
  .filter(line => line && !line.startsWith('#'));
const declared = entries('requirements.txt');
const locked = entries('requirements.lock.txt');
assert.ok(declared.length > 0, 'requirements.txt must declare a dependency');
assert.ok(locked.length > 0, 'requirements.lock.txt must freeze every dependency');
const declaredNames = declared.map(entry => {
  const match = entry.match(requirementName);
  assert.ok(match, `Invalid requirement declaration: ${entry}`);
  return match[1].toLowerCase();
});
const lockedNames = locked.map(entry => {
  const match = entry.match(frozenRequirement);
  assert.ok(match, `Lock entries must use exact versions: ${entry}`);
  return match[1].toLowerCase();
});
assert.deepEqual(declared, ['websockets>=15,<16'], 'Unexpected runtime dependency declaration');
assert.deepEqual(locked, ['websockets==15.0.1'], 'Frozen runtime dependency changed without review');
assert.equal(new Set(declaredNames).size, declaredNames.length, 'requirements.txt contains duplicate packages');
assert.equal(new Set(lockedNames).size, lockedNames.length, 'requirements.lock.txt contains duplicate packages');
assert.deepEqual([...lockedNames].sort(), [...declaredNames].sort(), 'Frozen requirements do not match declared packages');

const npmOutput = execFileSync('npm', ['pack', '--dry-run', '--ignore-scripts', '--json'], {
  cwd: root,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
});
const packed = JSON.parse(npmOutput)[0];
const names = packed.files.map(({path: file}) => file);
const required = [
  '.dockerignore',
  'AGENTS.md',
  'Dockerfile',
  'LICENSE',
  'README.md',
  'SECURITY.md',
  'THIRD_PARTY_NOTICES.md',
  'bin/fast-browser',
  'docs/desktop-companion.md',
  'ez-deployment.json',
  'ez-plugin.json',
  'package.json',
  'requirements.lock.txt',
  'requirements.txt',
  'scripts/release-check.mjs',
  'skills/fast-browser/SKILL.md',
  'src/cli.py',
  'src/companion.py',
  'src/runtime.py',
  'src/server.py',
];
for (const name of required) assert.ok(names.includes(name), `Packed artifact is missing ${name}`);
for (const entry of packageJson.files) {
  assert.ok(names.some(name => name === entry || name.startsWith(`${entry}/`)), `Declared package entry is missing: ${entry}`);
}
for (const name of names) {
  assert.ok(name === 'package.json' || packageJson.files.some(entry => name === entry || name.startsWith(`${entry}/`)), `Unallowlisted package entry: ${name}`);
  assert.ok(!name.startsWith('/') && !name.includes('\\') && !name.split('/').includes('..'), `Unsafe package path: ${name}`);
  assert.ok(!/(^|\/)(?:agent|node_modules|\.git|__pycache__|\.private|qa|plugin-manager-qa|spec-benchmark)(?:\/|$)|(^|\/)(?:principles|backlog|todo|sprints)\.md$|(^|\/)\.env(?:[./]|$)|(^|\/)\.npmrc$|(^|\/)\.DS_Store$|\.(?:pyc|tgz|log)$/i.test(name), `Unsafe package entry: ${name}`);
}

console.log(JSON.stringify({
  package: `${packageJson.name}@${packageJson.version}`,
  packageManager: packageJson.packageManager,
  frozenRequirements: locked,
  files: names,
  unpackedSize: packed.unpackedSize,
}, null, 2));
