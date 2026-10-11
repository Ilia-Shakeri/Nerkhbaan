import type { PricesResponse } from './api';

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
  })) };
}
