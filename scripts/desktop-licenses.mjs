import { readFileSync, readdirSync, realpathSync, existsSync } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';

const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const noticeName = /^(licen[sc]e|copying|copyright|notice)([.-]|$)/i;

function packageNotices(folder, prefix = '') {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true }).flatMap(file => {
    const relative = path.posix.join(prefix, file.name);
    if (file.isDirectory() && file.name !== 'node_modules' && !file.name.startsWith('.')) return packageNotices(folder, relative);
    if (!file.isFile() || !noticeName.test(file.name)) return [];
    const bytes = readFileSync(path.join(folder, relative));
    return [{ file: relative, sha256: digest(bytes), text: bytes.toString('utf8') }];
  });
}

export function desktopCssLicenseModules(root) {
  const entry = path.join(root, 'apps/web/src/styles/index.css');
  if (!existsSync(entry)) return [];
  const resolve = createRequire(path.join(root, 'package.json')).resolve;
  const visited = new Set(), modules = [];
  function visit(file) {
    if (visited.has(file)) return;
    visited.add(file);
    const css = readFileSync(file, 'utf8');
    for (const match of css.matchAll(/@import\s+['"]([^'"]+)['"]/g)) {
      const id = match[1];
      if (id.startsWith('.')) visit(path.resolve(path.dirname(file), id));
      else if (!/^(?:https?:|\/)/.test(id)) modules.push(resolve(id));
    }
  }
  visit(entry);
  return modules;
}

// Inventory the resolved build graph, including transformed CSS and conservative
// tree-shaken dependencies. Never infer permission from a package name alone.
export function collectDesktopLicenses(moduleIds, root) {
  root = realpathSync(root);
  const lock = JSON.parse(readFileSync(path.join(root, 'package-lock.json'), 'utf8'));
  const vendorRoot = path.join(root, 'scripts/vendor-licenses');
  const vendorManifest = path.join(vendorRoot, 'manifest.json');
  const supplements = existsSync(vendorManifest) ? JSON.parse(readFileSync(vendorManifest, 'utf8')) : {};
  const packages = new Map();
  const missingLicenses = new Set();
  for (const id of moduleIds) {
    if (id.startsWith('\0')) continue;
    const filename = id.split('?')[0];
    if (!path.isAbsolute(filename) || !existsSync(filename)) continue;
    let folder = path.dirname(realpathSync(filename));
    while (folder !== path.dirname(folder)) {
      const manifest = path.join(folder, 'package.json');
      if (existsSync(manifest)) {
        const meta = JSON.parse(readFileSync(manifest, 'utf8'));
        if (meta.name && meta.version) {
          const relative = path.relative(root, folder).replaceAll('\\', '/');
          if (relative.split('/').includes('node_modules')) {
            if (relative.startsWith('../') || !lock.packages[relative] || lock.packages[relative].version !== meta.version) {
              throw new Error(`Bundled dependency is outside the locked tree: ${meta.name}`);
            }
            if (!packages.has(relative)) {
              const files = packageNotices(folder).sort((a, b) => a.file.localeCompare(b.file, 'en'));
              const supplement = supplements[`${meta.name}@${meta.version}`];
              if (supplement) {
                if (!/^[\w.-]+$/.test(supplement.file) || supplement.package_integrity !== lock.packages[relative].integrity || !/^https:\/\/raw\.githubusercontent\.com\/[^/]+\/[^/]+\/[a-f0-9]{40}\//.test(supplement.source)) {
                  throw new Error(`Invalid pinned license supplement: ${meta.name}`);
                }
                const bytes = readFileSync(path.join(vendorRoot, supplement.file));
                if (digest(bytes) !== supplement.sha256) throw new Error(`License supplement changed: ${meta.name}`);
                files.push({ file: 'LICENSE.upstream', sha256: digest(bytes), text: bytes.toString('utf8'), source: supplement.source });
              }
              if (!meta.license || !files.some(file => /^(licen[sc]e|copying)([.-]|$)/i.test(file.file)) || files.some(file => !file.text.trim())) {
                missingLicenses.add(`${meta.name}@${meta.version}`);
              }
              if (lock.packages[relative].license !== meta.license) throw new Error(`Locked license differs: ${meta.name}`);
              packages.set(relative, { name: meta.name, version: meta.version, license: meta.license, lock_path: relative, files });
            }
          }
          break;
        }
      }
      folder = path.dirname(folder);
    }
  }
  if (missingLicenses.size) throw new Error(`Bundled dependency lacks license metadata/text: ${[...missingLicenses].sort().join(', ')}`);
  if (!packages.size) throw new Error('Desktop dependency inventory is empty');
  return [...packages.values()].sort((a, b) => a.lock_path.localeCompare(b.lock_path, 'en'));
}

export function desktopLicenses(root) {
  return {
    name: 'desktop-license-notices',
    apply: 'build',
    generateBundle() {
      // PostCSS consumes package imports before Rollup sees the CSS modules.
      const packages = collectDesktopLicenses([...this.getModuleIds(), ...desktopCssLicenseModules(root)], root);
      const inventory = { schema: 1, scope: 'Resolved desktop renderer build graph; conservative inclusion, not legal clearance or a runtime SBOM', packages };
      const text = packages.map(pkg => `${pkg.name}@${pkg.version} (${pkg.license})\n${pkg.files.map(file => `--- ${file.file} ---\n${file.text}`).join('\n')}`).join('\n\n========================================\n\n');
      this.emitFile({ type: 'asset', fileName: 'THIRD-PARTY-NOTICES.txt', source: text + '\n' });
      this.emitFile({ type: 'asset', fileName: 'desktop-dependencies.json', source: JSON.stringify(inventory, null, 2) + '\n' });
    },
  };
}
