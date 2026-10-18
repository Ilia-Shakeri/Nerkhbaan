import { expect, test, type Page } from '@playwright/test';

const credit = { label: 'نرخ‌سنج', url: 'https://nerkh.jahankhahan.shop/developers' };
const identities = [
  { instrument_id: 'GOLD_24K_REFERENCE_TOMAN_GRAM', label_fa: 'طلای ۲۴ عیار؛ مرجع ناشر', label_en: 'Published 24K gold reference',
    currency: 'TOMAN', method: 'published_reference', weight_unit: 'gram', nominal_karat: 24, is_derived: false, source_keys: ['gold24'] },
  { instrument_id: 'BTC_USD_IRAN_REFERENCE', label_fa: 'بیت‌کوین/دلار؛ مرجع محاسباتی ایران', label_en: 'BTC/USD Iranian reference valuation',
    currency: 'USD', method: 'iran_fx_ratio', weight_unit: 'unit', is_derived: true, source_keys: ['bitcoin', 'dollar'] },
  { instrument_id: 'USDT_USD_IRAN_REFERENCE', label_fa: 'تتر/دلار؛ مرجع محاسباتی ایران', label_en: 'USDT/USD Iranian reference valuation',
    currency: 'USD', method: 'iran_fx_ratio', weight_unit: 'unit', is_derived: true, source_keys: ['tether', 'dollar'] },
];

function response(revision: string, timeframe = '30d', available = true, ageSeconds = 2225) {
  const prices = [35000000, 80000, 0.9987];
  return { rights_revision: revision, timeframe, checked_at: new Date().toISOString(),
    attributions: [credit, { label: 'Unsafe credit', url: 'javascript:alert(1)' }], errors: [],
    references: identities.map((identity, index) => {
      const base = { ...identity, market: 'reference', region: 'iran', physical_purity_confirmed: false, purity: null,
        source_provider_id: 'nerkhsanj_reference_snapshot', attribution: credit, disclaimer_fa: 'نرخ مرجع',
        source_timezone: 'Asia/Tehran', source_calendar: 'jalali', source_observation_time_known: false };
      const history = available ? [
        { source_date: '1405/07/22', timestamp: '2026-10-13T20:30:00Z' },
        { source_date: '1405/07/24', timestamp: '2026-10-15T20:30:00Z' },
      ].map(day => ({ ...base, ...day, source_provider_id: 'nerkhsanj_reference_history',
        price: prices[index], price_decimal: String(prices[index]), source_time: null,
        source_timestamp_scope: 'source_reported_daily_close', timestamp_precision: 'day', timestamp_role: 'day_bucket_start',
        history_point_kind: index === 0 ? 'published_reference_daily_close' : 'same_day_iran_fx_ratio', inputs: [] })) : [];
      return { ...base, status: available ? 'delayed_reference' : 'unavailable_reference',
        current: { ...base, status: available ? 'delayed_reference' : 'unavailable_reference',
          price: available ? prices[index] : null, price_decimal: available ? String(prices[index]) : null,
          source_date: '1405/07/25', source_time: '16:16', observed_at: '2026-10-17T12:46:00Z',
          received_at: '2026-10-17T13:23:05Z', source_timestamp_scope: 'source_rates_last_change', source_timestamp_precision: 'minute',
          source_trade_time_known: false, age_seconds: ageSeconds, freshness_limit_seconds: index ? 60 : 300,
          maximum_reference_age_seconds: 86400, persistence_status: index === 2 ? 'unpersisted' : 'persisted',
          storage_fallback: index === 1, inputs: index ? [{ price: index === 1 ? 20000000000 : 249675 }, { price: 250000 }] : [] },
        history, history_status: available ? 'partial' : 'partial', history_time_info: { timestamp_precision: 'day',
          timestamp_role: 'day_bucket_start', source_timezone: 'Asia/Tehran', source_calendar: 'jalali', source_observation_time_known: false } };
    }) };
}

async function fixture(page: Page, language: 'fa' | 'en' = 'en') {
  const state = { revision: 'reference-first', available: true, ageSeconds: 2225, requests: [] as string[],
    gate: undefined as Promise<void> | undefined, gateRange: '1y', lateDone: false };
  await page.addInitScript(({ language }) => {
    localStorage.setItem('language', language); localStorage.setItem('currencyMode', 'usd');
    sessionStorage.setItem('splash-shown', 'true');
  }, { language });
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  await page.routeWebSocket('**/api/ws/prices', () => {});
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/me')) return route.fulfill({ json: { id: 1, username: 'reference_fixture', must_change_password: false } });
    if (url.pathname === '/api/prices') return route.fulfill({ json: { rights_revision: state.revision, source: {}, assets: [] } });
    if (url.pathname === '/api/prices/references') {
      const timeframe = url.searchParams.get('timeframe') ?? '30d';
      state.requests.push(timeframe);
      const body = response(state.revision, timeframe, state.available, state.ageSeconds);
      const gate = timeframe === state.gateRange ? state.gate : undefined;
      await gate;
      await route.fulfill({ json: body }).catch(() => {});
      if (gate) state.lateDone = true;
      return;
    }
    if (url.pathname.endsWith('/history')) return route.fulfill({ json: { rights_revision: state.revision, points: [] } });
    return route.fulfill({ json: [] });
  });
  return state;
}

for (const language of ['en', 'fa'] as const) {
  test(`Iranian references keep their method, delayed clock and published daily gaps (${language})`, async ({ page }, testInfo) => {
    const state = await fixture(page, language);
    await page.goto('/');
    const panel = page.locator('[data-reference-panel]');
    await panel.scrollIntoViewIfNeeded();
    const gold = panel.locator('[data-reference-card="gold24"]');
    const tether = panel.locator('[data-reference-card="usdt"]');
    await expect(gold.getByText(language === 'fa' ? 'مرجع با تأخیر' : 'Delayed reference', { exact: true })).toBeVisible();
    await expect(gold).toContainText(language === 'fa' ? 'خلوص دقیق تأیید نشده' : 'Exact purity is unconfirmed');
    await expect(gold).toContainText(language === 'fa' ? '۹۹۹۹ نیست' : 'not a 9999 bullion quote');
    await expect(tether.locator('[data-reference-price]')).toContainText(language === 'fa' ? '۰٫۹۹۸۷' : '0.9987');
    await expect(tether).toContainText(language === 'fa' ? 'نه قیمت بازار جهانی' : 'not a global exchange quote');
    await expect(tether.getByText(language === 'fa' ? 'ذخیره نشده' : 'Not saved', { exact: true })).toBeVisible();
    await expect(gold.locator('[data-reference-source-clock]')).toContainText(language === 'fa' ? '۱۶:۱۶' : '16:16');
    await expect(gold).toContainText(language === 'fa' ? '۳۷ دقیقه' : '37 minutes');
    await expect(panel.getByRole('link', { name: 'نرخ‌سنج' })).toHaveAttribute('href', credit.url);
    await expect(panel.getByRole('link', { name: 'Unsafe credit' })).toHaveCount(0);
    await expect(panel).not.toContainText('GOLD_24K_REFERENCE_TOMAN_GRAM');
    await gold.locator('summary').click();
    await expect(gold.locator('tbody tr')).toHaveCount(2);
    await expect(gold.getByRole('table')).toContainText(language === 'fa' ? '۱۴۰۵/۰۷/۲۲' : '1405/07/22');
    await expect(gold.getByRole('table')).not.toContainText(language === 'fa' ? '۱۴۰۵/۰۷/۲۳' : '1405/07/23');
    await expect(gold).toContainText(language === 'fa' ? 'ساعت ثبت موجود نیست' : 'observation time unavailable');
    await expect(gold.getByRole('table')).not.toContainText('00:00');
    await page.getByRole('button', { name: language === 'fa' ? 'تومان' : 'TMN', exact: true }).click();
    await panel.scrollIntoViewIfNeeded();
    await expect(tether.locator('[data-reference-price]')).toContainText(language === 'fa' ? '۰٫۹۹۸۷' : '0.9987');
    expect(state.requests).toEqual(['30d']);
    await panel.getByLabel(language === 'fa' ? 'بازهٔ آرشیو' : 'History period', { exact: true }).selectOption('1y');
    await expect.poll(() => state.requests).toEqual(['30d', '1y']);
    await expect(panel.locator('[data-reference-card]')).toHaveCount(3);
    await panel.screenshot({ path: testInfo.outputPath(`reference-panel-${language}.png`) });
  });
}

test('changed permissions remove reference values and reject an old in-flight HTTP result', async ({ page }) => {
  const state = await fixture(page);
  await page.goto('/');
  const panel = page.locator('[data-reference-panel]');
  await panel.scrollIntoViewIfNeeded();
  await expect(panel.locator('[data-reference-card="usdt"] [data-reference-price]')).toContainText('0.9987');
  let release!: () => void;
  state.gate = new Promise(resolve => { release = resolve; });
  await panel.getByLabel('History period', { exact: true }).selectOption('1y');
  await expect.poll(() => state.requests.length).toBe(2);
  state.revision = 'reference-withdrawn'; state.available = false;
  await page.evaluate(async () => { const client = await import('/src/app/services/api.ts'); await client.getPrices(); });
  await expect(panel.locator('[data-reference-card]')).toHaveCount(0);
  release();
  await expect.poll(() => state.lateDone).toBe(true);
  await expect(panel.locator('[data-reference-card]')).toHaveCount(0);
  await expect(panel).not.toContainText('0.9987');
  await expect(panel.getByRole('link', { name: 'نرخ‌سنج' })).toHaveCount(0);
});

test('reference polling pauses out of view and never overlaps a slow response', async ({ page }) => {
  await page.clock.install();
  const state = await fixture(page);
  await page.goto('/');
  const panel = page.locator('[data-reference-panel]');
  await panel.scrollIntoViewIfNeeded();
  await expect(panel.locator('[data-reference-card]')).toHaveCount(3);
  expect(state.requests).toEqual(['30d']);
  await page.getByRole('main').evaluate(element => element.scrollTo(0, 0));
  await expect.poll(() => panel.evaluate(element => element.getBoundingClientRect().top >= innerHeight)).toBe(true);
  await page.clock.fastForward(120000);
  expect(state.requests).toEqual(['30d']);
  let release!: () => void;
  state.gateRange = '30d'; state.gate = new Promise(resolve => { release = resolve; });
  await panel.scrollIntoViewIfNeeded();
  await expect.poll(() => state.requests.length).toBe(2);
  await page.clock.fastForward(180000);
  expect(state.requests).toEqual(['30d', '30d']);
  const aborted = page.waitForEvent('requestfailed', request => new URL(request.url()).pathname === '/api/prices/references');
  await page.getByRole('main').evaluate(element => element.scrollTo(0, 0));
  await aborted;
  await page.goto('/alerts');
  release();
  await expect.poll(() => state.lateDone).toBe(true);
  expect(state.requests).toEqual(['30d', '30d']);
});

test('a current reference and its numeric inputs disappear after the maximum age', async ({ page }) => {
  await page.clock.install();
  const state = await fixture(page);
  state.ageSeconds = 86399;
  await page.goto('/');
  const panel = page.locator('[data-reference-panel]');
  await panel.scrollIntoViewIfNeeded();
  await expect(panel.locator('[data-reference-card="usdt"] [data-reference-price]')).toContainText('0.9987');
  await expect(panel.locator('[data-reference-inputs]')).toHaveCount(2);
  await page.clock.fastForward(30000);
  await expect(panel.getByText('Unavailable', { exact: true })).toHaveCount(3);
  await expect(panel.locator('[data-reference-inputs]')).toHaveCount(0);
  await expect(panel.locator('[data-reference-price]').first()).toContainText('—');
  expect(state.requests).toEqual(['30d']);
});

test('unavailable references display a dash and logout rejects their late replies', async ({ page }) => {
  const state = await fixture(page);
  state.available = false;
  await page.goto('/');
  const panel = page.locator('[data-reference-panel]');
  await panel.scrollIntoViewIfNeeded();
  await expect(panel.locator('[data-reference-price]').first()).toContainText('—');
  await expect(panel.getByText('Unavailable', { exact: true })).toHaveCount(3);
  await expect(panel.locator('[data-reference-inputs]')).toHaveCount(0);
  let release!: () => void;
  state.available = true; state.gate = new Promise(resolve => { release = resolve; });
  await panel.getByLabel('History period', { exact: true }).selectOption('1y');
  await expect.poll(() => state.requests.length).toBe(2);
  await page.evaluate(async () => { const logout = await import('/src/app/services/logout-state.ts'); logout.beginLogout(); });
  release();
  await expect.poll(() => state.lateDone).toBe(true);
  await expect(page.locator('[data-reference-price]')).toHaveCount(0);
  const rejected = await page.evaluate(async () => {
    const client = await import('/src/app/services/api.ts');
    try { await client.getReferenceRates(); return false; } catch { return true; }
  });
  expect(rejected).toBe(true);
});
