import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

/** Strip nginx comments so assertions test directives, not prose. */
const withoutComments = (config) =>
  config
    .split("\n")
    .map((line) => line.replace(/#.*$/, ""))
    .join("\n");

/**
 * Split an nginx config into its `location` blocks.
 *
 * Brace-matched rather than regex-sliced, because the property under test is
 * exactly about what each block contains.
 */
const locationBlocks = (config) => {
  const blocks = [];
  const pattern = /location\s+([^{]+)\{/g;
  let match;
  while ((match = pattern.exec(config)) !== null) {
    let depth = 1;
    let index = pattern.lastIndex;
    while (index < config.length && depth > 0) {
      if (config[index] === "{") depth += 1;
      else if (config[index] === "}") depth -= 1;
      index += 1;
    }
    blocks.push({ selector: match[1].trim(), body: config.slice(pattern.lastIndex, index - 1) });
  }
  return blocks;
};

/** Blocks that return a status directly serve no content to protect. */
const servesContent = (block) =>
  !/^\s*return\s+\d+/m.test(block.body) &&
  // The ACME webroot serves only certbot's challenge token to a CA.
  !block.selector.includes(".well-known/acme-challenge");

for (const [label, configPath, snippetPath] of [
  ["web", "apps/web/nginx.conf", "apps/web/security-headers.conf"],
  ["admin", "apps/admin-web/nginx.conf", "apps/admin-web/security-headers.conf"],
  ["edge", "nginx/nginx.conf", "nginx/security-headers.inc"],
]) {
  test(`${label} proxy defines the browser security headers`, () => {
    const snippet = read(snippetPath);
    for (const header of [
      "Content-Security-Policy",
      "X-Frame-Options",
      "X-Content-Type-Options",
      "Referrer-Policy",
      "Cross-Origin-Opener-Policy",
    ]) {
      assert.match(snippet, new RegExp(`add_header ${header}`), `${label} missing ${header}`);
    }
  });

  test(`${label} proxy applies those headers in every location`, () => {
    // nginx drops inherited add_header directives in any location that
    // declares one of its own, so asserting the directives exist somewhere in
    // the file proves nothing: each serving location must include them.
    const config = withoutComments(read(configPath));
    for (const block of locationBlocks(config)) {
      if (!servesContent(block)) continue;
      assert.match(
        block.body,
        /include\s+\/etc\/nginx\/security-headers(-admin)?\.inc;/,
        `${label} location "${block.selector}" does not include the security headers`,
      );
    }
  });

  test(`${label} proxy does not forward a caller-supplied X-Forwarded-For`, () => {
    // $proxy_add_x_forwarded_for appends to whatever the client sent, leaving
    // the head of the chain attacker-controlled. Rate limits and the admin IP
    // allowlist both read that value.
    const config = withoutComments(read(configPath));
    assert.doesNotMatch(config, /\$proxy_add_x_forwarded_for/);
    assert.match(config, /proxy_set_header\s+X-Forwarded-For\s+\$remote_addr;/);
  });
}

test("edge proxy keeps metrics off the public host", () => {
  const config = withoutComments(read("nginx/nginx.conf"));
  assert.match(config, /location\s+\^~\s+\/metrics\s*\{\s*return 404;\s*\}/);
  assert.match(config, /location\s+\^~\s+\/api\/admin\s*\{\s*return 404;\s*\}/);
});

test("web keeps cookies while desktop uses secure native storage", () => {
  const api = read("apps/web/src/app/services/api.ts");
  assert.match(api, /withCredentials:\s*!isDesktop/);
  assert.match(api, /electronAPI\.auth\.setCredentials/);
  assert.doesNotMatch(api, /localStorage\.setItem\([^,]*(token|session)/i);
});

test("service worker cannot turn API routes into app shell", () => {
  const sw = read("apps/web/src/pwa/sw.ts");
  assert.match(sw, /denylist:\s*\[\/\^\\\/api\\\//);
});

test("service worker renders push payloads itself", () => {
  // A generated Workbox worker has no push listener, so the server-supplied
  // title and body would be dropped in favour of a browser default.
  const sw = read("apps/web/src/pwa/sw.ts");
  assert.match(sw, /addEventListener\("push"/);
  assert.match(sw, /addEventListener\("notificationclick"/);
  assert.match(sw, /showNotification/);

  const vite = read("apps/web/vite.config.ts");
  assert.match(vite, /strategies:\s*"injectManifest"/);
});

test("service worker does not seize control of a running page", () => {
  const vite = read("apps/web/vite.config.ts");
  assert.doesNotMatch(vite, /skipWaiting:\s*true/);
  assert.doesNotMatch(vite, /clientsClaim:\s*true/);
  assert.match(vite, /registerType:\s*"prompt"/);
});

test("push registration waits for an explicit opt-in", () => {
  // Prompting on load subscribes anonymous visitors and gets the prompt
  // auto-blocked by browsers.
  const register = read("apps/web/src/pwa/registerServiceWorker.ts");
  assert.doesNotMatch(register, /registerPushNotifications|enablePushNotifications/);

  const push = read("apps/web/src/pwa/push.ts");
  assert.match(push, /export async function enablePushNotifications/);
  assert.match(push, /export async function syncPushSubscription/);
  assert.match(push, /export async function disablePushNotifications/);
});

test("push subscriptions are rebound at sign-in and released at sign-out", () => {
  const context = read("apps/web/src/app/context/AppContext.tsx");
  assert.match(context, /syncPushSubscription/);
  assert.match(context, /disablePushNotifications/);
});

test("web ships only the font files the stylesheet references", () => {
  // The bundle previously carried every weight and legacy format of three
  // families: ~17 MB in the image, precached on first visit.
  const css = read("apps/web/src/styles/index.css");
  const referenced = new Set(
    [...css.matchAll(/fonts\/([A-Za-z0-9_/.-]+\.(?:woff2?|ttf|otf|eot))/g)].map(
      (match) => match[1].replace(/\\/g, "/"),
    ),
  );
  assert.ok(referenced.size > 0, "stylesheet references no fonts");

  const root = new URL("../apps/web/public/fonts/", import.meta.url);
  const shipped = readdirSync(root, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && /\.(woff2?|ttf|otf|eot)$/.test(entry.name))
    .map((entry) =>
      `${entry.parentPath ?? entry.path}/${entry.name}`
        .replace(/\\/g, "/")
        .split("/fonts/")[1],
    );

  for (const file of shipped) {
    assert.ok(referenced.has(file), `unused font shipped: ${file}`);
  }
  for (const file of referenced) {
    assert.ok(shipped.includes(file), `referenced font missing: ${file}`);
  }
});

test("desktop renderer keeps process and network guards", () => {
  const main = read("apps/desktop/electron/main.cjs");
  assert.match(main, /nodeIntegration:\s*false/);
  assert.match(main, /contextIsolation:\s*true/);
  assert.match(main, /sandbox:\s*true/);
  assert.match(main, /webSecurity:\s*true/);
  assert.match(main, /setWindowOpenHandler\(\(\) => \(\{ action: 'deny' \}\)\)/);
});
