import { expect, test } from '@playwright/test';

test('daily history keeps its date and source without claiming a precise observation hour', async ({ page }, testInfo) => {
  const revision = 'daily-history-fixture-v1';
  const day = { timestamp_precision: 'day', timestamp_role: 'day_bucket_start',
    source_observation_time_known: false, source_timezone: 'Asia/Tehran', source_date: '1405/07/23' };
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
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, username: 'daily_history_test', must_change_password: false } });
    if (path.endsWith('/prices')) return route.fulfill({ json: { rights_revision: revision, assets: [], source: {}, refreshed_at: '2026-10-17T00:00:00Z' } });
    if (path.endsWith('/history')) return route.fulfill({ json: { asset: path.includes('/silver/') ? 'silver' : 'gold', rights_revision: revision,
      toman_attributions: path.includes('/silver/') ? [{ label: 'Nerkhsanj', url: 'https://nerkh.jahankhahan.shop/developers' }] : [],
      points: path.includes('/silver/') ? [
        { timestamp: '2026-10-13T20:30:00Z', value_toman: 502340, value_usd: 54,
          time_info_toman: { ...day, source_date: '1405/07/22' }, time_info_usd: { timestamp_precision: 'instant' } },
        { timestamp: '2026-10-14T20:30:00Z', value_toman: 517260, value_usd: 55,
          time_info_toman: day, time_info_usd: { timestamp_precision: 'instant' } },
      ] : [] } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/');
  const chart = page.locator('[data-chart-interactive="true"]').filter({ has: page.locator('[data-history-precision="day"]') });
  await expect(chart).toHaveCount(1);
  await expect(chart.getByText('Includes daily closing rates', { exact: true })).toBeVisible();
  const lastTime = chart.locator('tbody tr').last().locator('td').first();
  await expect(lastTime).toContainText('15/10/2026');
  await expect(lastTime).toContainText('Daily close; observation time unavailable');
  await expect(lastTime).not.toContainText('00:00');
  await expect(page.getByRole('link', { name: 'Nerkhsanj', exact: true })).toBeVisible();
  await chart.screenshot({ path: testInfo.outputPath('daily-history.png') });
  await page.getByRole('button', { name: 'USD', exact: true }).click();
  await expect(page.locator('[data-history-precision="day"]')).toHaveCount(0);
  await expect(page.locator('[data-chart-interactive="true"] tbody tr').last().locator('td').first()).toContainText('00:00');
  await page.getByRole('button', { name: 'Show Silver chart in full screen' }).click();
  await expect(page.getByRole('dialog').locator('tbody tr').last().locator('td').first()).toContainText('00:00');
});
