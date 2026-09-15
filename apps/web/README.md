# nerkhbaan-web

The public progressive web app: price dashboard, charts, alerts, notifications
and the market assistant.

Part of the [Nerkhbaan monorepo](../../README.md). Run it from the repository
root — it resolves `@nerkhbaan/ui` and its environment file from there.

```bash
npm run dev:web      # http://127.0.0.1:5173
npm run build:web    # tsc --noEmit, then vite build
```

## Layout

```text
src/
├── app/
│   ├── components/   Error boundary, splash, modals
│   ├── context/      Auth, language, theme, currency
│   ├── layouts/      Desktop and mobile shells
│   ├── router/       Routes and the authenticated-route guard
│   ├── services/     api.ts — the single HTTP client
│   └── views/        One file per screen
├── pwa/
│   ├── sw.ts                    Service worker (injectManifest)
│   ├── push.ts                  Subscribe, sync, unsubscribe
│   └── registerServiceWorker.ts Registration and the update prompt
└── styles/           Tailwind layers, theme tokens, fonts
```

## Environment

Read from the repository root `.env` (`envDir` points there), inlined at build
time by Vite:

| Variable | Effect |
| --- | --- |
| `VITE_API_URL` | API origin. Leave empty in production — nginx proxies `/api/`. |
| `VITE_VAPID_PUBLIC_KEY` | Required for web push. Without it the browser cannot subscribe. |
| `VITE_WS_HEARTBEAT_TIMEOUT_MS` | Socket watchdog. Default 45 000. |

`VITE_VAPID_PUBLIC_KEY` is baked into the bundle. The Docker build takes it as a
build argument; an image built without it has push disabled until rebuilt.

## Live prices

The dashboard subscribes to `/api/ws/prices` and merges canonical updates into
the React Query cache, deduplicating by sequence number.

**Polling continues while the socket is connected**, slowly. Canonical events
are published only when a value *changes*, so a stalled pricing pipeline
produces heartbeats and no updates — which looks exactly like a quiet market.
The poll is the liveness check that distinguishes them.

## Interface and accessibility contracts

- The startup screen contains no market quote or chart. Only API-backed history
  may be presented as market data.
- Authentication uses a scrollable dynamic viewport with safe-area padding.
  Its normal card rotation remains, while the platform reduced-motion setting
  replaces movement with a minimal transition and skips the startup screen.
- Password fields expose one keyboard-reachable, localized reveal control.
- Interactive charts expose a spoken summary and the latest 20 real points as
  a screen-reader table. Chart cards also have keyboard move controls.
- Icon-only actions need localized accessible names. Popovers and toggles must
  expose their expanded or pressed state.
- Protected screens are route-level chunks. Keep public authentication eager so
  the first session does not download the full dashboard before sign-in.
- Shared dialogs contain focus, close with Escape or an outside click, restore
  the prior focus and body scroll state, and remain scrollable on short screens.
- Use one motion package, short non-bouncy springs, targeted properties, and
  reduced-motion fallbacks. Do not add blur or persistent `will-change` to
  repeated cards.
- Every visible control needs a working result. Failed requests must not look
  like empty data, and unavailable integrations need an honest state or retry.

## Service worker

Built with `injectManifest`, not `generateSW`, because the app needs its own
`push` and `notificationclick` handlers — a generated worker has neither, and
the server-supplied notification title and body would be dropped.

Updates use `registerType: "prompt"`. `skipWaiting` with `clientsClaim` swaps
the worker underneath an open session, so a deploy makes the running page
request chunk hashes that no longer exist. The new worker waits for the user.

## Assets

`public/fonts/` contains only the weights the stylesheet references. A contract
test in `scripts/frontend-contracts.test.mjs` fails the build if an unreferenced
font is added or a referenced one goes missing — the directory previously held
17 MB of unused weights and legacy formats, all precached on first visit.

## Notes

- `services/api.ts` is the only place that talks to the API. It owns the axios
  instance, refresh-on-401 with single-flight deduplication, and the error
  events the layout surfaces as toasts.
- Session state lives in `HttpOnly` cookies. Nothing auth-related is written to
  `localStorage`, and a contract test enforces that.
- The app is RTL-first. `dir` is set from the language context; use logical CSS
  properties (`ms-`, `me-`, `ps-`, `pe-`) rather than left/right.
