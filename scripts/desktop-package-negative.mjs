import assert from 'node:assert/strict';
import { extractAll, createPackage } from '@electron/asar';
import { mkdtemp, mkdir, writeFile, copyFile, readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const executable = process.env.NERKHBAAN_DESKTOP_EXECUTABLE || path.join(root, 'apps/desktop/release/win-unpacked/Nerkhbaan.exe');
const candidate = path.dirname(executable);
const fixture = await mkdtemp(path.join(process.env.NERKHBAAN_DESKTOP_NEGATIVE_ROOT || os.tmpdir(), 'nerkhbaan-private-path-negative-'));
const contents = path.join(fixture, 'archive-contents');
// Copy only the reviewed archive. The test fixture has no executable to launch.
extractAll(path.join(candidate, 'resources/app.asar'), contents);
await writeFile(path.join(contents, 'dist/.env.production'), 'FIXTURE_ONLY=never-a-real-secret\n');
await mkdir(path.join(fixture, 'resources'));
await createPackage(contents, path.join(fixture, 'resources/app.asar'));
for (const name of ['LICENSE-Nerkhbaan.txt', 'NOTICE-Nerkhbaan.txt', 'LICENSE-SCOPE.md']) {
  await copyFile(path.join(candidate, name), path.join(fixture, name));
}
const receipt = path.join(fixture, 'rejected.json');
const result = spawnSync(process.execPath, [path.join(root, 'scripts/desktop-smoke.mjs')], {
  encoding: 'utf8', timeout: 30_000, windowsHide: true, cwd: root,
  env: { ...process.env, NERKHBAAN_DESKTOP_EXECUTABLE: path.join(fixture, 'Nerkhbaan.exe'), NERKHBAAN_DESKTOP_SMOKE_RECEIPT: receipt },
});
await writeFile(path.join(fixture, 'failure.log'), result.stdout + result.stderr);
assert.equal(result.status, 1);
assert.match(result.stderr, /Private inputs and unreviewed runtime dependencies must not ship/);
const record = JSON.parse(await readFile(receipt, 'utf8'));
assert.equal(record.passed, false);
assert.equal(record.isolated_profile_removed, true);
assert.equal(record.endpoint_counts, undefined);
console.log(JSON.stringify({ fixture, rejected_before_launch: true, isolated_profile_removed: true, negative_control_passed: true }));
