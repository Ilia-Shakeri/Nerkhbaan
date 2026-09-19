import assert from "node:assert/strict";

test("owner facts and policy versions stay aligned without invented address", () => {
  const policies = read("apps/web/src/app/legal/policies.ts");
  const view = read("apps/web/src/app/views/LegalView.tsx");
  assert.match(policies, /Ilia Shakeri/);
  assert.match(policies, /ایلیا شاکری/);
  assert.match(policies, /Tehran, Iran/);
  assert.match(policies, /iliashkr@gmail\.com/);
  assert.match(policies, /We have no public postal address/);
  assert.match(policies, /The service is free now/);
  assert.match(view, /mailto:\$\{OPERATOR_EMAIL\}/);
  assert.doesNotMatch(view, /operator identity, public contact and retention periods need confirmation/);
  const version = policies.match(/POLICY_VERSION = '([^']+)'/)[1];
  for (const path of ['schemas.py', 'routers/support.py', 'routers/insights.py']) {
    assert.ok(read(`apps/api/app/${path}`).includes(`Literal["${version}"]`));
  }
});

test("legal pages are public and consent is never preselected", () => {
  const router = read("apps/web/src/app/router/AppRouter.tsx");
  const auth = read("apps/web/src/app/views/AuthView.tsx");
  const support = read("apps/web/src/app/views/SupportView.tsx");
  const chat = read("apps/web/src/app/views/AssistantView.tsx");
  assert.ok(router.indexOf("['privacy', 'terms', 'cookies', 'refunds', 'business']") < router.indexOf('path="/change-password"'));
  assert.match(auth, /acceptedTerms, setAcceptedTerms\] = useState\(false\)/);
  assert.match(auth, /dataConsent, setDataConsent\] = useState\(false\)/);
  assert.match(auth, /accepted_terms: acceptedTerms/);
  assert.match(auth, /policy_version: POLICY_VERSION/);
  assert.match(support, /!ticketConsent/);
  assert.match(support, /!replyConsent/);
  assert.match(chat, /!processingConsent/);
  assert.match(auth, /rotateY: isRtl \? -90 : 90/);
});

test("external charts never load tracking code and attribution remains", () => {
  const report = read("apps/web/src/app/views/AdvancedReportView.tsx");
  const dashboard = read("apps/web/src/app/views/DashboardView.tsx");
  assert.doesNotMatch(report, /createElement|<iframe|tv\.js|TradingView\.widget/);
  assert.match(report, /rel="noopener noreferrer"/);
  assert.match(dashboard, /attributionLogo: true/);
  assert.match(read("NOTICE"), /Copyright/);
});

test("cookie and chat lifetimes stay distinct in policy copy", () => {
  const policies = read("apps/web/src/app/legal/policies.ts");
  assert.match(policies, /15 minutes and 30 days/);
  assert.match(policies, /۱۵ دقیقه و ۳۰ روز/);
  assert.match(policies, /inactive for over 31 days/);
  assert.match(read("apps/api/app/config.py"), /auth_refresh_days: int = 30/);
  assert.match(read("apps/api/app/services/background.py"), /CHAT_RETENTION_DAYS = 31/);
});

test("legal body, focus and placeholder colours meet AA contrast pairs", () => {
  const lum = (hex) => {
    const values = hex.match(/[a-f0-9]{2}/gi).map((v) => parseInt(v, 16) / 255).map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
  };
  for (const [foreground, background] of [['E8D9AE', '0E0E0E'], ['3B2E13', 'FAF3E2'], ['686868', 'FFFFFF'], ['A3A3A3', '141414'], ['CDBB8C', '141414'], ['6A4E11', 'FAF3E2']]) {
    const [a, b] = [lum(foreground), lum(background)].sort((a, b) => b - a);
    assert.ok((a + 0.05) / (b + 0.05) >= 4.5, `${foreground}/${background}`);
  }
});
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

test("web image installer falls back only to its locked npm cache", () => {
  const installer = read("scripts/install-dependencies.sh");
  assert.match(installer, /install_from_cache\(\)/);
  assert.match(installer, /npm ci[\s\\]+--workspace=nerkhbaan-web[\s\\]+--workspace=@nerkhbaan\/ui[\s\\]+--include-workspace-root=false[\s\\]+--offline/);
  assert.match(installer, /Offline npm cache does not contain the locked dependency set/);
});

test("dashboard never makes a chart point from a live quote", () => {
  const dashboard = read("apps/web/src/app/views/DashboardView.tsx");
  assert.doesNotMatch(
    dashboard,
    /timestamp:\s*new Date\(\)\.toISOString\(\),\s*value_usd:\s*asset\.priceUsd/,
    "a live quote is not historical chart data",
  );
  assert.match(dashboard, /function ChartUnavailableState/);
  assert.match(dashboard, /historyQuery\?\.refetch/);
});

test("public splash never presents fixed market values as live data", () => {
  const splash = read("apps/web/src/app/components/SplashScreen.tsx");
  assert.doesNotMatch(splash, /const\s+TICKERS|Live Prices|قیمت‌های زنده/);
  assert.match(splash, /role="status"/);
});

test("authentication stays scrollable and exposes one keyboard password toggle", () => {
  const auth = read("apps/web/src/app/views/AuthView.tsx");
  const input = read("packages/ui/src/app/components/ui/input.tsx");
  assert.match(auth, /min-h-dvh/);
  assert.match(auth, /overflow-y-auto/);
  assert.match(auth, /dir="auto"/);
  assert.doesNotMatch(auth, /tabIndex=\{-1\}[\s\S]{0,300}Eye/);
  assert.match(auth, /rotateY:/, "the requested authentication card rotation must remain");
  assert.match(input, /aria-pressed=\{showPassword\}/);
});

test("motion and charts have accessible alternatives", () => {
  const app = read("apps/web/src/app/App.tsx");
  const dashboard = read("apps/web/src/app/views/DashboardView.tsx");
  const styles = read("apps/web/src/styles/index.css");
  assert.match(app, /MotionConfig reducedMotion="user"/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce/);
  assert.match(styles, /prefers-reduced-transparency:\s*reduce/);
  assert.match(dashboard, /ref=\{containerRef\}[\s\S]{0,160}role="img"/);
  assert.match(dashboard, /<table id=\{tableId\} className="sr-only">/);
  assert.match(dashboard, /Move .* card up|بردن کارت/);
});

test("admin navigation survives history and dangerous dialogs contain focus", () => {
  const app = read("apps/admin-web/src/App.tsx");
  const ui = read("apps/admin-web/src/ui.tsx");
  assert.match(app, /sectionFromHash/);
  assert.match(app, /hashchange/);
  assert.match(app, /aria-current=/);
  assert.match(app, /allowedNavigation\.some\(\(item\) => item\.id === section\)/);
  assert.match(ui, /event\.key === 'Escape'/);
  assert.match(ui, /busyRef\.current/);
  assert.match(ui, /event\.key !== 'Tab'/);
  assert.match(ui, /previousFocus\?\.focus\(\)/);
});

test("shared dialogs contain focus and restore page state", () => {
  const modal = read("packages/ui/src/app/components/ui/Modal.tsx");
  const uiPackage = JSON.parse(read("packages/ui/package.json"));
  assert.match(modal, /from 'motion\/react'/);
  assert.match(uiPackage.dependencies?.motion ?? "", /^\^11\./);
  assert.match(modal, /role="dialog"/);
  assert.match(modal, /event\.key === 'Escape'/);
  assert.match(modal, /event\.key !== 'Tab'/);
  assert.match(modal, /previousFocus\?\.focus\(\)/);
  assert.match(modal, /document\.body\.style\.overflow = previousOverflow/);
});

test("mobile navigation contains focus and restores its trigger", () => {
  const layout = read("apps/web/src/app/layouts/DesktopLayout.tsx");
  assert.match(layout, /mobileNavigationRef/);
  assert.match(layout, /role="dialog"/);
  assert.match(layout, /aria-modal="true"/);
  assert.match(layout, /event\.key !== 'Tab'/);
  assert.match(layout, /mobileMenuButtonRef\.current\?\.focus\(\)/);
});

test("secondary routes load on demand and analysis avoids unused history calls", () => {
  const router = read("apps/web/src/app/router/AppRouter.tsx");
  const analysis = read("apps/web/src/app/views/ChartAnalysisView.tsx");
  assert.match(router, /lazy\(\(\) => import\('\.\.\/views\/DashboardView'\)/);
  assert.match(router, /<Suspense/);
  assert.doesNotMatch(analysis, /getPriceHistory/);
  assert.match(analysis, /assetsLoadFailed/);
});

test("support and contact surfaces expose only working actions", () => {
  const support = read("apps/web/src/app/views/SupportView.tsx");
  const contact = read("apps/web/src/app/views/ContactView.tsx");
  assert.doesNotMatch(support, /Paperclip|Attach file|پیوست فایل/);
  assert.doesNotMatch(contact, /1234 5678|support@nerkhbaan\.com/);
  assert.match(contact, /navigate\('\/support'\)/);
});

test("production backup health fits inside the deployment wait window", () => {
  const compose = read("docker-compose.prod.yaml");
  const deploy = read("scripts/deploy-nerkhbaan-prod.sh");
  assert.match(compose, /db-backup:[\s\S]*healthcheck:[\s\S]*interval: 30s/);
  assert.match(compose, /HEALTHCHECK_PORT/);
  assert.match(deploy, /DEPLOY_WAIT_SECONDS="\$\{DEPLOY_WAIT_SECONDS:-240\}"/);
});
