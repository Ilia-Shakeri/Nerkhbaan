import { expect, test, type Page } from '@playwright/test';
import { emptyMarketPrices, mockMarketStream } from './market-fixture';

const ticket = { id: 71, subject: 'A support case', status: 'open', date: '2026-10-16', last_message: 'Initial case preview' };
const firstMessage = { id: 1, content: 'First message', from_user: 'user', timestamp: '2026-10-16T09:00:00Z' };

async function session(page: Page) {
  const state: { ticketFailure: boolean; messageFailure: boolean; answered: boolean; reads: number; gate?: Promise<void> } = { ticketFailure: false, messageFailure: false, answered: false, reads: 0 };
  await page.addInitScript(() => { if (!localStorage.getItem('language')) localStorage.setItem('language', 'en'); sessionStorage.setItem('splash-shown', 'true'); });
  await mockMarketStream(page);
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/me')) await route.fulfill({ json: { id: 1, username: 'interface_test', must_change_password: false } });
    else if (path.endsWith('/prices')) await route.fulfill({ json: emptyMarketPrices() });
    else if (path.endsWith('/history')) await route.fulfill({ json: { points: [] } });
    else if (path.endsWith('/notifications')) await route.fulfill({ json: [{ id: 4, title: 'Price threshold reached', message: 'Gold crossed your saved threshold. Review the price before acting.', created_at: '2026-10-16T09:00:00Z', read_at: null }] });
    else if (path.endsWith('/notifications/4/read')) await route.fulfill({ json: { id: 4, title: 'Price threshold reached', message: 'Gold crossed your saved threshold. Review the price before acting.', created_at: '2026-10-16T09:00:00Z', read_at: '2026-10-16T10:00:00Z' } });
    else if (path.endsWith('/support/ticket/71/messages')) {
      state.reads++;
      await state.gate;
      await route.fulfill(state.messageFailure ? { status: 503, json: { detail: 'Messages temporarily unavailable' } } : { json: state.answered ? [firstMessage, { id: 2, content: 'Fresh support answer', from_user: 'admin', timestamp: '2026-10-16T10:00:00Z' }] : [firstMessage] });
    } else if (path.endsWith('/support/ticket/72/messages')) await route.fulfill({ json: [{ id: 3, content: 'Second case reply', from_user: 'admin', timestamp: '2026-10-16T10:00:00Z' }] });
    else if (path.endsWith('/support/tickets')) await route.fulfill(state.ticketFailure ? { status: 503, json: { detail: 'Tickets temporarily unavailable' } } : { json: [{ ...ticket, status: state.answered ? 'answered' : 'open' }, { ...ticket, id: 72, subject: 'Second support case' }] });
    else await route.fulfill({ json: [] });
  });
  return state;
}

test('collapsed navigation retains all six accessible names', async ({ page }) => {
  await session(page);
  await page.goto('/');
  const collapse = page.getByRole('button', { name: 'Collapse sidebar', exact: true });
  await collapse.focus();
  await collapse.click();
  await expect(page.getByRole('button', { name: 'Expand sidebar', exact: true })).toBeVisible();
  for (const label of ['Dashboard', 'Alerts', 'Advanced Report', 'Smart Analysis', 'Smart Assistant', 'Settings']) {
    await expect(page.getByRole('link', { name: label, exact: true })).toBeVisible({ timeout: 1500 });
  }
  await page.getByRole('link', { name: 'Alerts', exact: true }).click();
  await expect(page).toHaveURL(/\/alerts$/);
});

test('notification shows title and distinct full message after marking it read', async ({ page }) => {
  await session(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Notifications', exact: true }).click();
  const row = page.getByRole('button', { name: /Price threshold reached/ });
  await expect(row).toContainText('Gold crossed your saved threshold. Review the price before acting.', { timeout: 1500 });
  const marked = page.waitForResponse(response => response.request().method() === 'PATCH' && new URL(response.url()).pathname.endsWith('/notifications/4/read'));
  await row.click();
  await marked;
  await expect(row.locator('span')).toHaveCount(0);
  await expect(row).toContainText('Gold crossed your saved threshold. Review the price before acting.');
});

test('ticket load failure stays distinct from empty data and can be retried', async ({ page }) => {
  const state = await session(page); state.ticketFailure = true;
  await page.goto('/support');
  const failure = page.getByRole('alert', { name: 'Ticket list unavailable' });
  await expect(failure).toBeVisible({ timeout: 2000 });
  await expect(page.getByText('No tickets yet', { exact: true })).toHaveCount(0);
  state.ticketFailure = false;
  await failure.getByRole('button', { name: 'Retry tickets' }).click();
  await expect(page.getByRole('button', { name: /A support case/ })).toBeVisible();
  await expect(failure).toHaveCount(0);
});

test('message load failure blocks reply and exposes an explicit retry', async ({ page }) => {
  const state = await session(page); state.messageFailure = true;
  await page.goto('/support');
  await page.getByRole('button', { name: /A support case/ }).click();
  const failure = page.getByRole('alert', { name: 'Ticket messages unavailable' });
  await expect(failure).toBeVisible({ timeout: 2000 });
  await expect(page.getByText('No messages yet', { exact: true })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Support reply' }).fill('Keep this draft');
  await page.getByRole('checkbox').check();
  await expect(page.getByRole('button', { name: 'Send support reply' })).toBeDisabled();
  state.messageFailure = false;
  await failure.getByRole('button', { name: 'Retry messages' }).click();
  await expect(page.getByText('First message', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Support reply' })).toHaveValue('Keep this draft');
  await expect(page.getByRole('button', { name: 'Send support reply' })).toBeEnabled();
});

test('open ticket refreshes replies and status without discarding draft or consent', async ({ page }) => {
  const state = await session(page);
  await page.goto('/support');
  await page.getByRole('button', { name: /A support case/ }).click();
  await expect(page.getByText('First message', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Support reply' }).fill('Draft stays here');
  await page.getByRole('checkbox').check();
  state.answered = true;
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.getByText('Fresh support answer', { exact: true })).toBeVisible({ timeout: 2000 });
  await expect(page.getByRole('button', { name: /A support case/ })).toContainText('Answered');
  await expect(page.getByRole('textbox', { name: 'Support reply' })).toHaveValue('Draft stays here');
  await expect(page.getByRole('checkbox')).toBeChecked();
  expect(state.reads).toBeGreaterThan(1);
});

test('visible ticket polls fresh replies while preserving the draft', async ({ page }) => {
  const state = await session(page);
  await page.clock.install();
  await page.goto('/support');
  await page.getByRole('button', { name: /A support case/ }).click();
  await expect(page.getByText('First message', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Support reply' }).fill('Draft through polling');
  state.answered = true;
  await page.clock.fastForward(15_000);
  await expect(page.getByText('Fresh support answer', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Support reply' })).toHaveValue('Draft through polling');
});

test('a late refresh from a previous ticket cannot replace the selected conversation', async ({ page }) => {
  const state = await session(page);
  await page.goto('/support');
  await page.getByRole('button', { name: /A support case/ }).click();
  await expect(page.getByText('First message', { exact: true })).toBeVisible();
  let release!: () => void;
  state.gate = new Promise<void>(resolve => { release = resolve; });
  state.answered = true;
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect.poll(() => state.reads).toBe(2);
  await page.getByRole('button', { name: /Second support case/ }).click();
  await expect(page.getByText('Second case reply', { exact: true })).toBeVisible();
  const lateResponse = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/support/ticket/71/messages'));
  release();
  await lateResponse;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await expect(page.getByRole('heading', { name: 'Second support case', exact: true })).toBeVisible();
  await expect(page.getByText('Fresh support answer', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Second case reply', { exact: true })).toBeVisible();
});


test('notification list fits the viewport in both directions and at large text sizes', async ({ page }) => {
  await session(page);
  await page.route('**/api/notifications', route => route.fulfill({ json: Array.from({length:20},(_,i)=>({id:i+50,title:'Price notice '+i,message:'Source https://example.com/'+ 'long-source-path'.repeat(12),created_at:'2026-11-24T09:00:00Z',read_at:null})) }));
  for (const width of [320,390,768,1365]) {
    await page.setViewportSize({width,height:844});
    for (const language of ['en','fa']) {
      await page.goto('/');
      await page.evaluate(language=>localStorage.setItem('language',language),language);await page.reload();
      await page.evaluate(()=>document.documentElement.style.fontSize='200%');
      await page.getByRole('button',{name:language==='fa'?'اعلان‌ها':'Notifications',exact:true}).click();
      const panel=page.locator('#notifications-panel');await expect(panel.getByText('Price notice 19',{exact:true})).toBeAttached();
      await expect.poll(async()=>{const r=(await panel.boundingBox())!;return r.x>=8&&r.x+r.width<=width-8&&r.y>=0&&r.y+r.height<=844;}).toBe(true);
      expect(await panel.evaluate(e=>e.scrollHeight>e.clientHeight)).toBe(true);
      expect(await panel.evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
      await page.setViewportSize({width,height:600});
      await expect.poll(async()=>{const r=(await panel.boundingBox())!;return r.y+r.height<=600;}).toBe(true);
      await page.setViewportSize({width,height:844});
      const last = panel.getByText('Price notice 19',{exact:true});await last.scrollIntoViewIfNeeded();await expect(last).toBeInViewport();
      await page.screenshot({path:test.info().outputPath('notice-'+width+'-'+language+'.png')});
      await page.keyboard.press('Escape');await expect(panel).toHaveCount(0);
    }
  }
});
