import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(path.join(root, file), "utf8").trim();
const version = read("VERSION");

assert.match(version, /^\d+\.\d+\.\d+$/, "VERSION must use major.minor.patch");

for (const manifest of [
  "package.json",
  "apps/web/package.json",
  "apps/admin-web/package.json",
  "apps/desktop/package.json",
  "packages/ui/package.json",
]) {
  const value = JSON.parse(read(manifest)).version;
  assert.equal(value, version, `${manifest} version must match VERSION`);
}

const lockfile = JSON.parse(read("package-lock.json"));
assert.equal(lockfile.version, version, "package-lock.json version must match VERSION");
assert.equal(lockfile.packages[""].version, version, "root lockfile version must match VERSION");

assert.match(
  read("apps/api/app/release.py"),
  new RegExp(`VERSION = \"${version.replaceAll(".", "\\.")}\"`),
  "API release version must match VERSION",
);

assert.match(read("CHANGELOG.md"), new RegExp(`## \\[${version.replaceAll(".", "\\.")}\\]`));
assert.match(
  read("apps/web/src/app/components/SplashScreen.tsx"),
  new RegExp(`APP_VERSION = 'v${version.replaceAll(".", "\\.")}'`),
  "web release label must match VERSION",
);
console.log(`Release version ${version} is consistent.`);
