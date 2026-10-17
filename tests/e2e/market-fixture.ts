import type { Page } from '@playwright/test';

const revision = 'empty-market-fixture-v1';

export function emptyMarketPrices() {
  return { rights_revision: revision, assets: [], source: {}, refreshed_at: '2026-10-17T00:00:00Z' };
}

export async function mockMarketStream(page: Page) {
  await page.route('**/*', route => {
    const host = new URL(route.request().url()).hostname;
    return ['127.0.0.1', 'localhost'].includes(host) ? route.continue() : route.abort();
  });
  await page.routeWebSocket('**/api/ws/prices', socket => {
    socket.send(JSON.stringify({ event_type: 'snapshot', rights_revision: revision, prices: [] }));
  });
}
