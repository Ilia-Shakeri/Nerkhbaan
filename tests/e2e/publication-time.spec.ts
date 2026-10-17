import { expect, test, type WebSocketRoute } from '@playwright/test';

test('publication clocks stay on their currency leg through HTTP and socket updates', async ({ page }, testInfo) => {
  const revision = 'publication-clock-fixture-v1';
  const summary = { source_timestamp_scope: 'publication_snapshot', source_timestamp_precision: 'minute',
    source_trade_time_known: false, source_timezone: 'Asia/Tehran' };
  const silver = { asset: 'silver', label_fa: 'نقره', label_en: 'Silver', price_usd: 55, price_toman: 500000,
    change_percent: null, trend: 'neutral', history: [], source_usd: 'canonical', source_toman: 'canonical',
    usd_status: 'live', toman_status: 'live', stale_minutes: 0, chart_error: false, chart_error_message: { fa: '', en: '' },
    usd_observed_at: '2026-10-17T11:47:12Z', toman_observed_at: '2026-10-17T11:46:00Z',
    usd_source_summary: {}, toman_source_summary: summary };
  let socket: WebSocketRoute | undefined;
  await page.addInitScript(() => {
    localStorage.setItem('language', 'en');
    localStorage.setItem('currencyMode', 'toman');
    sessionStorage.setItem('splash-shown', 'true');
  });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort());
  await page.routeWebSocket('**/api/ws/prices', route => { socket = route; });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, username: 'publication_clock_test', must_change_password: false } });
    if (path.endsWith('/prices')) return route.fulfill({ json: { rights_revision: revision, assets: [silver], source: {}, refreshed_at: '2026-10-17T11:47:18Z' } });
    if (path.endsWith('/history')) return route.fulfill({ json: { asset: 'silver', rights_revision: revision, points: [] } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/');
  const details = page.locator('[data-price-details="silver"]');
  const clock = details.locator('[data-publication-clock="true"]');
  await expect(details.getByText('Publication time; trade time unknown', { exact: true })).toBeVisible();
  await expect(clock).toContainText('15:16');
  await expect(clock).not.toContainText('15:16:00');
  await expect.poll(() => Boolean(socket)).toBe(true);
  await page.getByRole('button', { name: 'USD', exact: true }).click();
  await expect(clock).toHaveCount(0);
  socket!.send(JSON.stringify({ event_type: 'canonical_update', rights_revision: revision,
    instrument_id: 'XAG_USD_OZ', compatibility_asset: 'silver', price: 56, status: 'live', sequence: 1,
    observed_at: '2026-10-17T11:49:37Z', canonical_at: '2026-10-17T11:49:38Z',
    source_summary: { source_timestamp_scope: 'response_quote_snapshot', source_timestamp_precision: 'second',
      source_trade_time_known: false, source_timezone: 'UTC' } }));
  await expect(clock).toContainText('11:49:37');
  await page.getByRole('button', { name: 'TMN', exact: true }).click();
  await expect(clock).toContainText('15:16');
  await expect(clock).not.toContainText('11:49:37');
  await details.screenshot({ path: testInfo.outputPath('publication-clock.png') });
  socket!.send(JSON.stringify({ event_type: 'canonical_update', rights_revision: revision,
    instrument_id: 'XAG_USD_OZ', compatibility_asset: 'silver', price: 57, status: 'live', sequence: 2,
    observed_at: '2026-10-17T11:50:41Z', canonical_at: '2026-10-17T11:50:42Z' }));
  await expect(clock).toContainText('15:16');
  await page.getByRole('button', { name: 'USD', exact: true }).click();
  await expect(clock).toHaveCount(0);
});
