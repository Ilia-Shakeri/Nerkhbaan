import { expect, test } from '@playwright/test';
import { randomBytes } from 'node:crypto';

test('changing reference periods during a slow read can retry the cancelled period immediately', async ({ page }) => {
  const id = `reference_${randomBytes(6).toString('hex')}`;
  const signup = await page.request.post('http://127.0.0.1:43187/api/auth/signup', {
    headers: { Origin: 'http://127.0.0.1:43188' },
    data: { username: id, email: `${id}@example.com`, full_name: 'Reference recovery test',
      password: 'LocalReference42!Password', accepted_terms: true,
      account_data_consent: true, policy_version: '2026-09-19.2' },
  });
  expect(signup.status()).toBe(201);
  await page.addInitScript(() => {
    localStorage.setItem('language', 'en');
    sessionStorage.setItem('splash-shown', 'true');
  });
  const reads: string[] = [];
  await page.route('**/api/prices/references?**', async route => {
    const period = new URL(route.request().url()).searchParams.get('timeframe')!;
    reads.push(period);
    const response = await route.fetch();
    if (reads.length === 1) await new Promise(resolve => setTimeout(resolve, 1500));
    await route.fulfill({ response }).catch(() => {});
  });
  await page.goto('/');
  const period = page.getByRole('combobox', { name: 'History period' });
  await period.scrollIntoViewIfNeeded();
  await expect.poll(() => reads.filter(value => value === '30d').length).toBe(1);
  await period.selectOption('1y');
  await expect.poll(() => reads.includes('1y')).toBe(true);
  await period.selectOption('30d');
  await expect.poll(() => reads.filter(value => value === '30d').length, { timeout: 6000 }).toBe(2);
});
