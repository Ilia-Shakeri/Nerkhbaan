import type { PricesResponse, SourceAttribution } from './api';

export const PRICING_RIGHTS_EVENT = 'pricing-rights-changed';
let rightsRevision = '';
let rightsEpoch = 0;
let rightsPending = false;
const retiredSocketRevisions = new Set<string>();

export const currentRightsRevision = (): string => rightsRevision;
export const currentRightsEpoch = (): number => rightsEpoch;
export const rightsArePending = (): boolean => rightsPending;

export function acceptRightsRevision(value: unknown, origin: 'http' | 'socket', requestEpoch = rightsEpoch): boolean {
  const next = typeof value === 'string' && value.length <= 128 ? value.trim() : '';
  if (origin === 'http' && requestEpoch !== rightsEpoch) return false;
  if (!next) return !rightsRevision && !rightsPending;
  if (origin === 'socket') {
    if (rightsPending) return false;
    if (next === rightsRevision) return true;
    if (retiredSocketRevisions.has(next)) return false;
    // Hashes carry no ordering. A new socket hint must be confirmed by a fresh read.
    rightsPending = true;
    rightsEpoch += 1;
    window.dispatchEvent(new CustomEvent(PRICING_RIGHTS_EVENT, { detail: { revision: rightsRevision, epoch: rightsEpoch, origin } }));
    return false;
  }
  const changed = next !== rightsRevision;
  const wasPending = rightsPending;
  if (changed) {
    if (rightsRevision) retiredSocketRevisions.add(rightsRevision);
    rightsRevision = next;
    rightsEpoch += 1;
  }
  rightsPending = false;
  if (changed || wasPending) window.dispatchEvent(new CustomEvent(PRICING_RIGHTS_EVENT, { detail: { revision: next, epoch: rightsEpoch, origin } }));
  return true;
}

export function safeAttributions(value: unknown): SourceAttribution[] {
  if (!Array.isArray(value)) return [];
  const result: SourceAttribution[] = [];
  for (const entry of value.slice(0, 64)) {
    if (!entry || typeof entry !== 'object' || typeof entry.label !== 'string' || typeof entry.url !== 'string' || entry.url.length > 2048) continue;
    const label = entry.label.trim().slice(0, 120);
    if (!label || /[\u0000-\u001f\u007f]/.test(label)) continue;
    try {
      const url = new URL(entry.url);
      if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) continue;
      if (!result.some(item => item.label === label && item.url === url.href)) result.push({ label, url: url.href });
    } catch { /* Ignore malformed source links. */ }
  }
  return result;
}

export function canonicalLegDetails(payload: Record<string, unknown>, isToman: boolean): Record<string, unknown> {
  const leg = isToman ? 'toman' : 'usd';
  const unit = typeof payload.currency === 'string' && typeof payload.unit === 'string' ? {
    instrument_id: String(payload.instrument_id), quote_currency: payload.currency,
    weight_unit: payload.unit, purity: typeof payload.purity === 'number' && Number.isFinite(payload.purity) ? payload.purity : null,
    market: typeof payload.market === 'string' ? payload.market : '',
    display_decimals: typeof payload.display_decimals === 'number' ? payload.display_decimals : 0,
  } : null;
  return {
    [`instrument_id_${leg}`]: payload.instrument_id,
    [`unit_${leg}`]: unit,
    [`change_percent_${leg}`]: typeof payload.change_24h === 'number' && Number.isFinite(payload.change_24h) ? payload.change_24h : null,
    [`${leg}_attributions`]: safeAttributions(payload.attribution),
    [`${leg}_observed_at`]: typeof payload.observed_at === 'string' ? payload.observed_at : null,
    [`${leg}_source_summary`]: payload.source_summary && typeof payload.source_summary === 'object'
      && !Array.isArray(payload.source_summary) ? payload.source_summary : null,
  };
}

export function clearSnapshotPrices(current: PricesResponse | undefined): PricesResponse | undefined {
  if (!current) return current;
  return { ...current, assets: current.assets.map(asset => ({
    ...asset, price_usd: null, price_toman: null,
    usd_status: 'unavailable', toman_status: 'unavailable',
    source_usd: 'unavailable', source_toman: 'unavailable',
    candidate_price_usd: null, candidate_price_toman: null,
    change_percent_usd: null, change_percent_toman: null, change_percent: null,
    candidate_provider: null, candidate_observed_at: null, difference_percent: null,
    verification_status: null, observed_at: null, canonical_at: null, age_seconds: null,
    source_summary: null,
    usd_source_summary: null, toman_source_summary: null,
    usd_observed_at: null, toman_observed_at: null,
    history: [], usd_attributions: [], toman_attributions: [],
  })) };
}
