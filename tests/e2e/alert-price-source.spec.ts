import { expect, test, type Page } from '@playwright/test';

type AlertRecord = Record<string, unknown>;

async function mockAlerts(page: Page, language: 'fa' | 'en', initial: AlertRecord[] = []) {
  const mutations: Array<{ method: string; body: AlertRecord }> = [];
  let alerts = initial;
  await page.addInitScript(({ language }) => {
    localStorage.setItem('language', language);
    localStorage.setItem('currencyMode', 'toman');
    sessionStorage.setItem('splash-shown', 'true');
  }, { language });
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort());
  await page.routeWebSocket('**/api/ws/prices', () => {});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, username: 'alert_price_test', must_change_password: false } });
    if (/\/alerts(?:\/\d+)?$/.test(path)) {
      if (route.request().method() === 'GET') return route.fulfill({ json: alerts });
      const body = route.request().postDataJSON() as AlertRecord;
      mutations.push({ method: route.request().method(), body });
      const id = Number(path.split('/').at(-1)) || mutations.length;
      const saved = { id, alert_type: 'price', formula: null, is_active: true,
        price_source_mode: 'ordinary', ...alerts.find(alert => alert.id === id), ...body };
      alerts = [...alerts.filter(alert => alert.id !== id), saved];
      return route.fulfill({ json: saved });
    }
    if (path.endsWith('/prices')) return route.fulfill({ json: { rights_revision: 'alert-price-fixture-v1', assets: [], source: {} } });
    if (path.endsWith('/history')) return route.fulfill({ json: { asset: 'gold', rights_revision: 'alert-price-fixture-v1', points: [] } });
    return route.fulfill({ json: [] });
  });
  return mutations;
}

for (const language of ['en', 'fa'] as const) {
  for (const flow of ['alerts', 'dashboard'] as const) {
    test(`${flow} explicitly saves reference alerts and resets to market prices (${language})`, async ({ page }, testInfo) => {
      const mutations = await mockAlerts(page, language);
      await page.goto(flow === 'alerts' ? '/alerts' : '/');
      const open = () => page.getByRole('button', { name: flow === 'alerts'
        ? language === 'fa' ? 'هشدار جدید' : 'New Alert'
        : language === 'fa' ? 'ساخت هشدار برای طلا' : 'Create an alert for Gold', exact: true }).click();
      await open();
      const choice = page.getByLabel(language === 'fa' ? 'مبنای قیمت' : 'Price used', { exact: true });
      await expect(choice).toHaveValue('ordinary');
      await choice.selectOption('reference');
      await expect(page.getByText(language === 'fa'
        ? 'هشدار با نرخ مرجعِ تازه سنجیده می‌شود؛ این نرخ ممکن است با قیمت معامله فرق داشته باشد.'
        : 'Uses fresh published reference rates, which may differ from trading prices.', { exact: true })).toBeVisible();
      await page.getByRole('spinbutton').fill('1250');
      const save = () => page.getByRole('button', { name: flow === 'alerts'
        ? language === 'fa' ? 'ایجاد' : 'Create'
        : language === 'fa' ? 'ذخیره' : 'Save Alert', exact: true }).click();
      if (language === 'fa') await choice.locator('..').screenshot({ path: testInfo.outputPath(`${flow}-price-choice-fa.png`) });
      await save();
      await expect.poll(() => mutations.length).toBe(1);
      expect(mutations[0]).toMatchObject({ method: 'POST', body: { price_source_mode: 'reference', currency_mode: 'toman', asset: 'gold', target_price: 1250 } });
      await expect(choice).toHaveCount(0);
      await open();
      await expect(choice).toHaveValue('ordinary');
      await page.getByRole('spinbutton').fill('1350');
      await save();
      await expect.poll(() => mutations.length).toBe(2);
      expect(mutations[1].body).toMatchObject({ price_source_mode: 'ordinary', target_price: 1350 });
    });
  }
}

for (const savedMode of ['reference', 'derived', 'legacy-unrecognized']) {
  test(`editing a saved ${savedMode} alert preserves its price policy`, async ({ page }) => {
    const mutations = await mockAlerts(page, 'en', [{ id: 7, asset: 'gold', condition: 'above', target_price: 1250,
      currency_mode: 'toman', price_source_mode: savedMode, notify_app: true, notify_email: false,
      alert_type: 'price', is_active: true }]);
    await page.goto('/alerts');
    await page.getByRole('button', { name: 'Edit Alert', exact: true }).click();
    await expect(page.getByLabel('Price used', { exact: true })).toHaveValue(savedMode === 'legacy-unrecognized' ? '' : savedMode);
    await page.getByLabel('Target', { exact: true }).fill('1350');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect.poll(() => mutations.length).toBe(1);
    expect(mutations[0].method).toBe('PATCH');
    expect(mutations[0].body.target_price).toBe(1350);
    if (savedMode === 'legacy-unrecognized') expect(mutations[0].body).not.toHaveProperty('price_source_mode');
    else expect(mutations[0].body.price_source_mode).toBe(savedMode);
  });
}
