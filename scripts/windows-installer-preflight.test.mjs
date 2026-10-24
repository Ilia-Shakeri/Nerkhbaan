import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';

const root = path.resolve(import.meta.dirname, '..');
function fixture(t) {
  const temporary = mkdtempSync(path.join(os.tmpdir(), 'installer-preflight-guard-'));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  return temporary;
}
function run(directory, extra = [], installer = 'unused.exe', unpacked = 'unused') {
  return spawnSync('powershell.exe', ['-NoProfile', '-File', path.join(root, 'scripts/windows-installer-preflight.ps1'),
    '-InstallerPath', installer, '-UnpackedPath', unpacked, '-EvidenceDirectory', directory, ...extra],
  { cwd: root, encoding: 'utf8', timeout: 20_000, windowsHide: true });
}
test('unsigned preflight needs explicit opt-in and makes no evidence or installation', { skip: process.platform !== 'win32' }, t => {
  const directory = path.join(fixture(t), 'evidence');
  const result = run(directory);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Explicit unsigned preflight opt-in/);
  assert.equal(existsSync(directory), false);
});
test('existing evidence is preserved and a repeated installation cannot start', { skip: process.platform !== 'win32' }, t => {
  const directory = fixture(t), receipt = path.join(directory, 'unsigned-installer-acceptance.json');
  const old = '{"accepted_unsigned_install":false,"state":"previous failure"}';
  writeFileSync(receipt, old);
  const result = run(directory, ['-AllowUnsignedTest']);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /fresh evidence directory/);
  assert.equal(readFileSync(receipt, 'utf8'), old);
});
test('wrong product version is rejected before an installer is launched', { skip: process.platform !== 'win32' }, t => {
  const temporary = fixture(t), unpacked = path.join(temporary, 'unpacked');
  mkdirSync(unpacked);
  const result = run(path.join(temporary, 'evidence'), ['-AllowUnsignedTest'], process.execPath, unpacked);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Candidate product version does not match/);
});
