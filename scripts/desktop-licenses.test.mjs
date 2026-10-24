import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { collectDesktopLicenses, desktopLicenses, desktopCssLicenseModules, privateDesktopPaths } from './desktop-licenses.mjs';

function fixture(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'desktop-license-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const folder = path.join(root, 'node_modules', 'fixture');
  mkdirSync(path.join(folder, 'dist'), { recursive: true });
  const source = path.join(folder, 'dist', 'index.js');
  writeFileSync(source, 'export const value = 1;');
  const metadata = { name: 'fixture', version: '1.0.0', license: 'MIT' };
  writeFileSync(path.join(folder, 'package.json'), JSON.stringify(metadata));
  writeFileSync(path.join(folder, 'LICENSE'), 'Copyright fixture\nPermission granted for this test.');
  writeFileSync(path.join(folder, 'NOTICE.txt'), 'Keep this attribution.');
  const lock = { packages: { 'node_modules/fixture': metadata } };
  const saveLock = () => writeFileSync(path.join(root, 'package-lock.json'), JSON.stringify(lock));
  saveLock();
  return { root, folder, source, lock, saveLock };
}

test('bundled notices preserve copyright and NOTICE, deduplicate modules and omit host paths', t => {
  const f = fixture(t), emitted = [];
  const plugin = desktopLicenses(f.root);
  plugin.generateBundle.call({ getModuleIds: () => [f.source, f.source + '?commonjs-proxy', '\0virtual'], emitFile: asset => emitted.push(asset) });
  assert.equal(emitted.length, 2);
  assert.match(emitted.find(file => file.fileName.endsWith('.txt')).source, /Copyright fixture[\s\S]*Keep this attribution/);
  const json = emitted.find(file => file.fileName.endsWith('.json')).source;
  assert.equal(JSON.parse(json).packages.length, 1);
  assert.ok(!json.includes(f.root));
  assert.equal(JSON.parse(json).packages[0].files[0].sha256.length, 64);
});

test('dependency absent from lock fails before creating distributable notices', t => {
  const f = fixture(t); f.lock.packages = {}; f.saveLock();
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /outside the locked tree/);
});
test('installed version drift fails', t => {
  const f = fixture(t); f.lock.packages['node_modules/fixture'].version = '2.0.0'; f.saveLock();
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /outside the locked tree/);
});
test('missing and blank license text fail even when manifest says MIT', t => {
  const f = fixture(t);
  rmSync(path.join(f.folder, 'LICENSE'));
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /lacks license/);
  writeFileSync(path.join(f.folder, 'LICENSE'), ' ');
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /lacks license/);
});
test('license drift fails and cannot silently relabel third-party code', t => {
  const f = fixture(t); f.lock.packages['node_modules/fixture'].license = 'Apache-2.0'; f.saveLock();
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /Locked license differs/);
});
test('CSS dependency modules keep their notices', t => {
  const f = fixture(t), css = path.join(f.folder, 'style.css'); writeFileSync(css, '.x{color:red}');
  assert.equal(collectDesktopLicenses([css], f.root)[0].name, 'fixture');
});
test('empty resolved dependency graph cannot pass the inventory gate', t => {
  const f = fixture(t);
  assert.throws(() => collectDesktopLicenses(['\0internal', '/missing.js'], f.root), /empty/);
});

function supplement(f) {
  const folder = path.join(f.root, 'scripts/vendor-licenses');
  mkdirSync(folder, { recursive: true });
  rmSync(path.join(f.folder, 'LICENSE'));
  const text = 'Copyright upstream\nMIT permission for fixture';
  writeFileSync(path.join(folder, 'fixture-LICENSE.txt'), text);
  const entry = { file: 'fixture-LICENSE.txt', sha256: '94e7', source: `https://raw.githubusercontent.com/owner/repo/${'a'.repeat(40)}/LICENSE`, package_integrity: 'sha512-fixture' };
  f.lock.packages['node_modules/fixture'].integrity = entry.package_integrity; f.saveLock();
  return { folder, entry, save: () => writeFileSync(path.join(folder, 'manifest.json'), JSON.stringify({ 'fixture@1.0.0': entry })) };
}
test('modified vendored license is rejected', t => {
  const f = fixture(t), s = supplement(f); s.save();
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /supplement changed/);
});
test('vendored license cannot refer outside its directory or cover another package integrity', t => {
  const f = fixture(t), s = supplement(f); s.entry.file = '../LICENSE'; s.save();
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /Invalid pinned/);
  s.entry.file = 'fixture-LICENSE.txt'; s.entry.package_integrity = 'another'; s.save();
  assert.throws(() => collectDesktopLicenses([f.source], f.root), /Invalid pinned/);
});
test('licenses of bundled nested vendors are preserved alongside the package license', t => {
  const f = fixture(t), nested = path.join(f.folder, 'lib-vendor/d3');
  mkdirSync(nested, { recursive: true }); writeFileSync(path.join(nested, 'LICENSE'), 'Copyright nested vendor');
  assert.equal(collectDesktopLicenses([f.source], f.root)[0].files.find(file => file.file === 'lib-vendor/d3/LICENSE').text, 'Copyright nested vendor');
});
test('package imports consumed by PostCSS still enter the license inventory', t => {
  const f = fixture(t), styles = path.join(f.root, 'apps/web/src/styles');
  mkdirSync(styles, { recursive: true });
  writeFileSync(path.join(styles, 'index.css'), '@import "./theme.css";');
  writeFileSync(path.join(styles, 'theme.css'), '@import "fixture/dist/index.js";');
  assert.deepEqual(desktopCssLicenseModules(f.root), [f.source]);
  assert.equal(collectDesktopLicenses(desktopCssLicenseModules(f.root), f.root)[0].name, 'fixture');
});
test('archive policy rejects dotenv variants, private folders and Windows case/path forms', () => {
  const forbidden = ['/dist/.env', '/dist/.env.production', '/.env.local', '\\dist\\.ENV.PRODUCTION', '/.local-keys/key', '/.git/config', '/node_modules/pkg/index.js'];
  assert.deepEqual(privateDesktopPaths(forbidden), forbidden);
  assert.deepEqual(privateDesktopPaths(['/dist/assets/index.js', '/dist/desktop-dependencies.json', '/electron/main.cjs']), []);
});
