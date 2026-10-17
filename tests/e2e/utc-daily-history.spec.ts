import { expect, test } from '@playwright/test';

test('UTC daily chart labels keep the source day without an observation hour', async ({ page }, testInfo) => {
  const revision = 'utc-daily-history-fixture-v1';
  const day = { timestamp_precision: 'day', timestamp_role: 'day_bucket_start',
    source_observation_time_known: false, source_timezone: 'UTC', source_calendar: 'gregorian' };
  await page.addInitScript(() => {
    localStorage.setItem('language', 'en');
    localStorage.setItem('currencyMode', 'toman');
    sessionStorage.setItem('splash-shown', 'true');
  });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort());
  await page.routeWebSocket('**/api/ws/prices', () => {});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, username: 'utc_day_test', must_change_password: false } });
    if (path.endsWith('/prices')) return route.fulfill({ json: { rights_revision: revision, assets: [], source: {}, refreshed_at: '2026-10-17T00:00:00Z' } });
    if (path.endsWith('/history')) return route.fulfill({ json: { asset: 'silver', rights_revision: revision,
      points: path.includes('/silver/') ? [
        { timestamp: '2026-10-13T00:00:00Z', value_toman: 465000, value_usd: null,
          time_info_toman: { ...day, source_date: '2026-10-13' } },
        { timestamp: '2026-10-14T00:00:00Z', value_toman: 467000, value_usd: null,
          time_info_toman: { ...day, source_date: '2026-10-14' } },
      ] : [] } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/');
  const chart = page.locator('[data-chart-interactive="true"]').filter({ has: page.locator('[data-history-precision="day"]') });
  await expect(chart).toHaveCount(1);
  const lastTime = chart.locator('tbody tr').last().locator('td').first();
  await expect(lastTime).toContainText('14/10/2026');
  await expect(lastTime).toContainText('Daily close; observation time unavailable');
  await expect(lastTime).not.toContainText('00:00');
  await chart.screenshot({ path: testInfo.outputPath('utc-daily-history.png') });
});
