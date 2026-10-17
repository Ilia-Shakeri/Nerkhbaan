import { expect, test, type Page, type WebSocketRoute } from '@playwright/test';

const profile = { id: 1, username: 'rights_fixture', full_name: 'Rights Fixture', email: 'rights@example.invalid', is_active: true, must_change_password: false, created_at: '2026-10-17T00:00:00Z' };
const credit = { label: 'Gold API', url: 'https://gold-api.com/' };
const gold = { asset: 'gold', label_fa: 'طلا', label_en: 'Gold', price_usd: 2080, price_toman: null,
  change_percent: null, change_percent_usd: null, trend: 'neutral', history: [], source_usd: 'canonical', source_toman: 'unavailable',
  usd_status: 'live', toman_status: 'unavailable', stale_minutes: 0, chart_error: false, chart_error_message: { fa: '', en: '' },
  usd_attributions: [credit, { label: 'Unsafe credit', url: 'javascript:alert(1)' }], toman_attributions: [] };

async function fixture(page: Page) {
  const state = { revision: 'first', visible: true, historyGate: undefined as Promise<void> | undefined,
    analysisGate: undefined as Promise<void> | undefined, notificationGate: undefined as Promise<void> | undefined,
    noticeRequests: 0, lateNoticeDone: false, analyzing: false, socket: undefined as WebSocketRoute | undefined };
  await page.addInitScript(() => {
    localStorage.setItem('language', 'en');
    localStorage.setItem('currencyMode', 'usd');
    sessionStorage.setItem('splash-shown', 'true');
  });
  await page.route('**/*', route => {
    const host = new URL(route.request().url()).hostname;
    return ['127.0.0.1', 'localhost'].includes(host) ? route.continue() : route.abort();
  });
  await page.routeWebSocket('**/api/ws/prices', socket => { state.socket = socket; });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: profile });
    if (url.pathname === '/api/prices') return route.fulfill({ json: { rights_revision: state.revision,
      refreshed_at: '2026-10-17T00:00:00Z', source: {}, assets: state.visible ? [gold] : [] } });
    if (url.pathname.endsWith('/history')) {
      const revision = state.revision;
      const visible = state.visible;
      if (url.searchParams.get('timeframe') === '7d') await state.historyGate;
      return route.fulfill({ json: { asset: 'gold', rights_revision: revision,
        usd_attributions: visible ? [{ label: 'History source', url: 'https://history.fixture.invalid/' }] : [],
        toman_attributions: [], points: visible ? [
          { timestamp: '2026-10-16T12:00:00Z', value_usd: 2070, value_toman: null },
          { timestamp: '2026-10-17T00:00:00Z', value_usd: 2080, value_toman: null },
        ] : [] } }).catch(() => {});
    }
    if (url.pathname.endsWith('/sources')) return route.fulfill({ json: { instrument_id: 'XAU_USD_OZ', sources: [
      { provider_name: 'Stored source quote', price: 2080, status: 'live', currency: 'USD', observed_at: '2026-10-17T00:00:00Z' },
    ] } });
    if (url.pathname === '/api/insights/analyze') {
      state.analyzing = true;
      await state.analysisGate;
      return route.fulfill({ json: { asset: 'gold', analysis: 'Old market analysis must stay hidden' } }).catch(() => {});
    }
    if (url.pathname === '/api/notifications') {
      state.noticeRequests++;
      const visible = state.visible;
      const gate = visible ? state.notificationGate : undefined;
      await gate;
      await route.fulfill({ json: visible ? [{ id: 1, title: 'Market notice', message: 'Old notice price 2080 must disappear',
        resource_type: 'alert_trigger', resource_id: '1', severity: 'warning', created_at: '2026-10-17T00:00:00Z' }] : [] }).catch(() => {});
      if (gate) state.lateNoticeDone = true;
      return;
    }
    return route.fulfill({ json: [] });
  });
  return state;
}

test('source credits show safe current and historical contributors', async ({ page }) => {
  await fixture(page);
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Gold API', exact: true }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: 'Gold API', exact: true }).first()).toHaveAttribute('href', credit.url);
  await expect(page.getByText('Unsafe credit', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'History source', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Show Gold chart in full screen' }).click();
  await expect(page.getByRole('dialog').getByRole('link', { name: 'History source', exact: true })).toBeVisible();
});

test('changed source rights clear source panel and reject late history and old socket frames', async ({ page }) => {
  const state = await fixture(page);
  let releaseHistory!: () => void;
  state.historyGate = new Promise(resolve => { releaseHistory = resolve; });
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Gold API', exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Compare sources', exact: true }).first().click();
  await expect(page.getByText('Stored source quote', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '7d', exact: true }).first().click();
  await expect.poll(() => Boolean(state.socket)).toBe(true);
  state.revision = 'second'; state.visible = false;
  state.socket!.send(JSON.stringify({ event_type: 'heartbeat', rights_revision: 'second' }));
  releaseHistory();
  state.socket!.send(JSON.stringify({ event_type: 'canonical_update', rights_revision: 'first', instrument_id: 'XAU_USD_OZ',
    compatibility_asset: 'gold', price: 9999, status: 'live', sequence: 999, attribution: [credit] }));
  await expect(page.getByRole('link', { name: 'Gold API', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'History source', exact: true })).toHaveCount(0);
  await expect(page.getByText('Stored source quote', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/9,999/)).toHaveCount(0);
});

test('source-rights change clears analysis and ignores a late provider reply', async ({ page }) => {
  const state = await fixture(page);
  let releaseAnalysis!: () => void;
  state.analysisGate = new Promise(resolve => { releaseAnalysis = resolve; });
  await page.goto('/analysis');
  await page.getByRole('button', { name: /^Gold/ }).click();
  await expect.poll(() => state.analyzing).toBe(true);
  state.revision = 'second'; state.visible = false;
  await page.evaluate(async () => {
    const client = await import('/src/app/services/api.ts');
    await client.getPrices();
  });
  releaseAnalysis();
  await expect(page.getByText('Old market analysis must stay hidden', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Gold/ })).toHaveCount(0);
});

test('source-rights change clears an open notification and rejects its late reload', async ({ page }) => {
  const state = await fixture(page);
  await page.goto('/');
  const bell = page.getByRole('button', { name: 'Notifications', exact: true });
  await bell.click();
  await expect(page.getByText('Old notice price 2080 must disappear', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  let releaseNotice!: () => void;
  state.notificationGate = new Promise(resolve => { releaseNotice = resolve; });
  await bell.click();
  await expect.poll(() => state.noticeRequests).toBe(2);
  state.revision = 'second'; state.visible = false;
  await page.evaluate(async () => {
    const client = await import('/src/app/services/api.ts');
    await client.getPrices();
  });
  releaseNotice();
  await expect.poll(() => state.lateNoticeDone).toBe(true);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.getByText('Old notice price 2080 must disappear', { exact: true })).toHaveCount(0);
});
