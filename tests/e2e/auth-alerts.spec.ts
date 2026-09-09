import { expect, test } from '@playwright/test';

test('user signs up and manages an alert', async ({ page }) => {
  const nonce = Date.now();
  const email = `browser.${nonce}@example.com`;

  await page.addInitScript(() => localStorage.setItem('language', 'en'));
  await page.goto('/auth');
  await page.getByRole('button', { name: 'Sign up' }).click();
  await page.getByLabel('Full Name').fill('Browser Test User');
  await page.getByLabel('Username').fill(`browser_${nonce}`);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('BrowserPass123!');
  await page.getByRole('button', { name: 'Create Account' }).click();

  await expect(page).toHaveURL('/');
  await page.goto('/alerts');
  await page.getByRole('button', { name: 'New Alert' }).click();
  await page.getByLabel('Target').fill('1250');
  await page.getByRole('button', { name: 'Create', exact: true }).click();

  await expect(page.getByText('$1,250')).toBeVisible();
  await page.getByRole('button', { name: 'Edit Alert' }).click();
  await page.getByLabel('Target').fill('1350');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('$1,350')).toBeVisible();

  await page.getByRole('button', { name: 'Alert removed' }).click();
  await expect(page.getByText('No alerts yet')).toBeVisible();
});
