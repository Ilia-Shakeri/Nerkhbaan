import { test } from '@playwright/test';

export function adminTestUrl(path = '/') {
  const configured = new URL(String(test.info().project.use.baseURL || 'http://127.0.0.1:4174'));
  if (!['localhost', '127.0.0.1'].includes(configured.hostname)) throw new Error('Administrator fixtures require a local server');
  if (configured.port === '4173') configured.port = '4174';
  return new URL(path, configured.origin).href;
}
