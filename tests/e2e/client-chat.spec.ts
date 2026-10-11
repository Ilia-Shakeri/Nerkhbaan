import { expect, test } from '@playwright/test';

test('a saved reply remains visible when refreshing the chat list fails', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('language', 'en'));
  await page.route('**/api/auth/me', route => route.fulfill({ json: { id: 1, username: 'chat_test', full_name: 'Chat Test', email: 'chat@example.com', must_change_password: false } }));
  let saved = false;
  const session = { id: 1, title: 'Saved chat', updated_at: '2026-10-11T00:00:00Z', messages: [{ role: 'user', content: 'First question' }, { role: 'assistant', content: 'Saved server reply' }] };
  await page.route('**/api/insights/chat/sessions', route => route.fulfill(saved ? { status: 503, json: { detail: 'Temporary list failure' } } : { json: [] }));
  await page.route('**/api/insights/chat/sessions/1', route => route.fulfill({ json: session }));
  await page.route('**/api/insights/chat', async route => { saved = true; await route.fulfill({ json: { session_id: 1, reply: 'Saved server reply' } }); });
  await page.goto('/assistant', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'New chat' }).click();
  await page.getByRole('textbox', { name: 'Question for assistant' }).fill('First question');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('Saved server reply', { exact: true })).toBeVisible();
  await expect(page.getByText('Chat list could not refresh; your reply was saved.', { exact: true })).toBeVisible();
  await expect(page.getByText('Saved server reply', { exact: true })).toBeVisible();
});
