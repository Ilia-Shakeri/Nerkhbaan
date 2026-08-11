import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("web proxy sends browser security headers", () => {
  const nginx = read("apps/web/nginx.conf");
  for (const header of [
    "Content-Security-Policy",
    "X-Frame-Options",
    "Cross-Origin-Opener-Policy",
    "Cross-Origin-Resource-Policy",
  ]) {
    assert.match(nginx, new RegExp(`add_header ${header}`));
  }
});

test("web session stays in secure cookies", () => {
  const api = read("apps/web/src/app/services/api.ts");
  assert.match(api, /withCredentials:\s*true/);
  assert.doesNotMatch(api, /localStorage\.setItem\([^,]*(token|session)/i);
});

test("service worker cannot turn API routes into app shell", () => {
  const vite = read("apps/web/vite.config.ts");
  assert.match(vite, /navigateFallbackDenylist:\s*\[\/\^\\\/api\\\//);
});

test("desktop renderer keeps process and network guards", () => {
  const main = read("apps/desktop/electron/main.cjs");
  assert.match(main, /nodeIntegration:\s*false/);
  assert.match(main, /contextIsolation:\s*true/);
  assert.match(main, /sandbox:\s*true/);
  assert.match(main, /webSecurity:\s*true/);
  assert.match(main, /setWindowOpenHandler\(\(\) => \(\{ action: 'deny' \}\)\)/);
});
