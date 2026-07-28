import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ColorType, CrosshairMode, LineSeries, createChart, type IChartApi, type ISeriesApi, type LineData, type Time, type UTCTimestamp } from 'lightweight-charts';
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellPlus, ArrowUpRight, ArrowDownRight, Webhook, Mail, Smartphone, AlertTriangle, Maximize2, ChevronDown, Database } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { useAppContext } from '../context/AppContext';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { toast } from 'sonner';
import {
  api,
  formatPrice,
  getPriceHistory,
  getPrices,
  getPricesWebSocketUrl,
  queryKeys,
  type CurrencyMode,
  type InstrumentSourcesResponse,
  type OperationalPriceStatus,
  type PriceAsset,
  type PricesResponse,
  type PriceTimeframe,
} from '../services/api';

type AssetId = 'gold' | 'silver' | 'usdt' | 'btc';

type AssetPoint = {
  timestamp: string;
  value_usd: number | null;
  value_toman: number | null;
};

type AssetCard = {
  id: AssetId;
  label: { fa: string; en: string };
  priceUsd: number | null;
  priceToman: number | null;
  changePercent: number;
  isUp: boolean;
  history: AssetPoint[];
  sourceUsd: string;
  sourceToman: string;
  usdStatus: OperationalPriceStatus;
  tomanStatus: OperationalPriceStatus;
  staleMinutes: number | null;
  chartError: boolean;
  chartErrorMessage: { fa: string; en: string };
  observedAt: string | null;
  canonicalAt: string | null;
  ageSeconds: number | null;
  sourceSummary: string | Record<string, unknown> | null;
  candidatePriceUsd: number | null;
  candidatePriceToman: number | null;
  candidateProvider: string | null;
  candidateObservedAt: string | null;
  differencePercent: number | null;
  verificationStatus: string | null;
};

const CHART_ORDER_STORAGE_KEY = 'dashboard-chart-order-v3';
const DEFAULT_ASSET_ORDER: AssetId[] = ['gold', 'silver', 'usdt', 'btc'];
const TIMEFRAMES: PriceTimeframe[] = ['1h', '24h', '7d', '30d', '1y'];
const DEFAULT_TIMEFRAMES: Record<AssetId, PriceTimeframe> = {
  gold: '24h',
  silver: '24h',
  usdt: '24h',
  btc: '24h',
};

const CHART_COLORS: Record<AssetId, { dark: string; light: string }> = {
  gold: { dark: '#D4AF37', light: '#B8860B' },
  silver: { dark: '#C0C8D8', light: '#7F8896' },
  usdt: { dark: '#22C55E', light: '#16A34A' },
  btc: { dark: '#F7931A', light: '#D97706' }
};

const STATUS_COLORS: Record<OperationalPriceStatus, { dark: string; light: string }> = {
  live: { dark: 'bg-emerald-500/10 text-emerald-400', light: 'bg-emerald-100 text-emerald-700' },
  fresh_cache: { dark: 'bg-sky-500/10 text-sky-300', light: 'bg-sky-100 text-sky-700' },
  cached: { dark: 'bg-sky-500/10 text-sky-300', light: 'bg-sky-100 text-sky-700' },
  verifying: { dark: 'bg-yellow-500/10 text-yellow-300', light: 'bg-yellow-100 text-yellow-800' },
  suspicious: { dark: 'bg-orange-500/10 text-orange-300', light: 'bg-orange-100 text-orange-800' },
  suspicious_unconfirmed: { dark: 'bg-orange-500/10 text-orange-300', light: 'bg-orange-100 text-orange-800' },
  derived_fallback: { dark: 'bg-purple-500/10 text-purple-300', light: 'bg-purple-100 text-purple-800' },
  stale: { dark: 'bg-amber-500/10 text-amber-300', light: 'bg-amber-100 text-amber-800' },
  expired: { dark: 'bg-red-500/10 text-red-300', light: 'bg-red-100 text-red-800' },
  unpersisted: { dark: 'bg-blue-500/10 text-blue-300', light: 'bg-blue-100 text-blue-800' },
  unavailable: { dark: 'bg-red-500/10 text-red-400', light: 'bg-red-100 text-red-700' }
};

const INSTRUMENT_IDS: Record<AssetId, Record<CurrencyMode, string>> = {
  gold: { usd: 'XAU_USD_OZ', toman: 'GOLD_18K_TOMAN_GRAM' },
  silver: { usd: 'XAG_USD_OZ', toman: 'SILVER_999_TOMAN_GRAM' },
  usdt: { usd: 'USDT_USD', toman: 'USDT_TOMAN' },
  btc: { usd: 'BTC_USD', toman: 'BTC_TOMAN' },
};

const ASSET_LABELS: Record<AssetId, { fa: string; en: string }> = {
  gold: { fa: 'طلا', en: 'Gold' },
  silver: { fa: 'نقره', en: 'Silver' },
  usdt: { fa: 'تتر', en: 'Tether' },
  btc: { fa: 'بیت کوین', en: 'Bitcoin' }
};

const getInitialAssetOrder = (): AssetId[] => {
  if (typeof window === 'undefined') {
    return DEFAULT_ASSET_ORDER;
  }
  try {
    const rawValue = window.localStorage.getItem(CHART_ORDER_STORAGE_KEY);
    if (!rawValue) {
      return DEFAULT_ASSET_ORDER;
    }
    const parsed = JSON.parse(rawValue);
    if (!Array.isArray(parsed)) {
      return DEFAULT_ASSET_ORDER;
    }
    const validIds = new Set(DEFAULT_ASSET_ORDER);
    const savedIds = parsed.filter(
      (value): value is AssetId => typeof value === 'string' && validIds.has(value as AssetId)
    );
    const missingIds = DEFAULT_ASSET_ORDER.filter((id) => !savedIds.includes(id));
    return [...savedIds, ...missingIds];
  } catch {
    return DEFAULT_ASSET_ORDER;
  }
};

const buildPlaceholderAsset = (id: AssetId): PriceAsset => ({
  asset: id,
  label_fa: ASSET_LABELS[id].fa,
  label_en: ASSET_LABELS[id].en,
  price_usd: null,
  price_toman: null,
  change_percent: Number.NaN,
  trend: 'up',
  source_usd: 'unavailable',
  source_toman: 'unavailable',
  usd_status: 'unavailable',
  toman_status: 'unavailable',
  stale_minutes: null,
  chart_error: true,
  chart_error_message: { fa: 'امکان دریافت اطلاعات وجود ندارد', en: 'Unable to fetch data' },
  history: [],
  observed_at: null,
  canonical_at: null,
  age_seconds: null,
});

const EMPTY_ASSETS: PriceAsset[] = DEFAULT_ASSET_ORDER.map(buildPlaceholderAsset);

const normalizeStatus = (value: unknown): OperationalPriceStatus => {
  if (value === 'confirmed') return 'live';
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(STATUS_COLORS, value)
    ? value as OperationalPriceStatus
    : 'unavailable';
};

const buildLiveCard = (asset: PriceAsset | undefined, id: AssetId): AssetCard => {
  if (!asset) {
    const placeholder = buildPlaceholderAsset(id);
    return {
      id,
      label: { fa: placeholder.label_fa, en: placeholder.label_en },
      priceUsd: placeholder.price_usd,
      priceToman: placeholder.price_toman,
      changePercent: placeholder.change_percent,
      isUp: placeholder.trend === 'up',
      history: placeholder.history,
      sourceUsd: placeholder.source_usd,
      sourceToman: placeholder.source_toman,
      usdStatus: placeholder.usd_status,
      tomanStatus: placeholder.toman_status,
      staleMinutes: placeholder.stale_minutes,
      chartError: placeholder.chart_error,
      chartErrorMessage: placeholder.chart_error_message,
      observedAt: null,
      canonicalAt: null,
      ageSeconds: null,
      sourceSummary: null,
      candidatePriceUsd: null,
      candidatePriceToman: null,
      candidateProvider: null,
      candidateObservedAt: null,
      differencePercent: null,
      verificationStatus: null,
    };
  }
  return {
    id,
    label: { fa: asset.label_fa, en: asset.label_en },
    priceUsd: asset.price_usd,
    priceToman: asset.price_toman,
    changePercent: asset.change_percent,
    isUp: asset.trend === 'up',
    history: asset.history,
    sourceUsd: asset.source_usd,
    sourceToman: asset.source_toman,
    usdStatus: normalizeStatus(asset.usd_status),
    tomanStatus: normalizeStatus(asset.toman_status),
    staleMinutes: asset.stale_minutes,
    chartError: asset.chart_error,
    chartErrorMessage: asset.chart_error_message,
    observedAt: asset.observed_at ?? null,
    canonicalAt: asset.canonical_at ?? null,
    ageSeconds: asset.age_seconds ?? (asset.stale_minutes === null ? null : asset.stale_minutes * 60),
    sourceSummary: asset.source_summary ?? null,
    candidatePriceUsd: asset.candidate_price_usd ?? null,
    candidatePriceToman: asset.candidate_price_toman ?? null,
    candidateProvider: asset.candidate_provider ?? null,
    candidateObservedAt: asset.candidate_observed_at ?? null,
    differencePercent: asset.difference_percent ?? null,
    verificationStatus: asset.verification_status ?? null,
  };
};

const formatAge = (seconds: number | null, language: 'fa' | 'en'): string => {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return language === 'fa' ? 'نامشخص' : 'Unknown';
  const rounded = Math.floor(seconds);
  if (rounded < 60) return language === 'fa' ? `${rounded} ثانیه` : `${rounded}s`;
  if (rounded < 3600) return language === 'fa' ? `${Math.floor(rounded / 60)} دقیقه` : `${Math.floor(rounded / 60)}m`;
  if (rounded < 86400) return language === 'fa' ? `${Math.floor(rounded / 3600)} ساعت` : `${Math.floor(rounded / 3600)}h`;
  return language === 'fa' ? `${Math.floor(rounded / 86400)} روز` : `${Math.floor(rounded / 86400)}d`;
};

const parseChartTimestamp = (timestamp: string): number => {
  const value = timestamp.trim();
  const hasTimeZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return Date.parse(hasTimeZone ? value : `${value}Z`);
};

const chartTimeToDate = (time: Time): Date | null => {
  if (typeof time === 'number') return new Date(time * 1_000);
  if (typeof time === 'string') {
    const milliseconds = parseChartTimestamp(time);
    return Number.isFinite(milliseconds) ? new Date(milliseconds) : null;
  }
  return new Date(Date.UTC(time.year, time.month - 1, time.day));
};

const formatChartDateTime = (time: Time, language: 'fa' | 'en'): string => {
  const date = chartTimeToDate(time);
  if (!date) return '';
  return new Intl.DateTimeFormat(language === 'fa' ? 'fa-IR' : 'en-GB', {
    timeZone: 'Asia/Tehran',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
};

const formatChartTick = (time: Time, language: 'fa' | 'en'): string => {
  const date = chartTimeToDate(time);
  if (!date) return '';
  return new Intl.DateTimeFormat(language === 'fa' ? 'fa-IR' : 'en-GB', {
    timeZone: 'Asia/Tehran',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
};

const toChartValue = (point: AssetPoint, mode: CurrencyMode, usdToTomanRate: number | null) => {
  const raw = mode === 'usd' ? point.value_usd : point.value_toman;
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) return raw;

  const other = mode === 'usd' ? point.value_toman : point.value_usd;
  if (typeof other !== 'number' || !Number.isFinite(other) || other <= 0 || !usdToTomanRate) return null;
  const converted = mode === 'usd' ? other / usdToTomanRate : other * usdToTomanRate;
  return Number.isFinite(converted) && converted > 0 ? converted : null;
};

const toChartData = (
  points: AssetPoint[],
  mode: CurrencyMode,
  usdToTomanRate: number | null,
): LineData<UTCTimestamp>[] => {
  const unique = new Map<number, number>();
  for (const point of points) {
    const milliseconds = parseChartTimestamp(point.timestamp);
    const value = toChartValue(point, mode, usdToTomanRate);
    if (!Number.isFinite(milliseconds) || value === null) continue;
    unique.set(Math.floor(milliseconds / 1_000), value);
  }
  return [...unique.entries()]
    .sort(([left], [right]) => left - right)
    .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
};

function FinancialChart({
  data,
  color,
  isDark,
  currencyMode,
  language,
  className = 'h-[400px] min-h-[400px]',
}: {
  data: LineData<UTCTimestamp>[];
  color: string;
  isDark: boolean;
  currencyMode: CurrencyMode;
  language: 'fa' | 'en';
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [crosshairPoint, setCrosshairPoint] = useState<{ value: number; time: Time } | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#AA986A' : '#7A5E24',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(212,175,55,0.06)' : 'rgba(122,94,36,0.08)' },
        horzLines: { color: isDark ? 'rgba(212,175,55,0.10)' : 'rgba(122,94,36,0.12)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color, labelBackgroundColor: color },
        horzLine: { color, labelBackgroundColor: color },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 3,
        barSpacing: 8,
        minBarSpacing: 2,
        tickMarkFormatter: (time: Time) => formatChartTick(time, language),
      },
      handleScale: true,
      handleScroll: true,
      localization: {
        locale: language === 'fa' ? 'fa-IR' : 'en-US',
        priceFormatter: (value: number) => formatPrice(value, currencyMode, language),
        timeFormatter: (time: Time) => formatChartDateTime(time, language),
      },
    });
    const series = chart.addSeries(LineSeries, {
      color,
      lineWidth: 3,
      priceLineVisible: true,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 5,
    });

    chart.subscribeCrosshairMove((event) => {
      const point = event.seriesData.get(series);
      setCrosshairPoint(
        event.time && point && 'value' in point && typeof point.value === 'number'
          ? { value: point.value, time: event.time }
          : null,
      );
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [color, currencyMode, isDark, language]);

  useEffect(() => {
    seriesRef.current?.setData(data);
    if (data.length > 0) chartRef.current?.timeScale().fitContent();
  }, [data]);

  return (
    <div className={`relative w-full ${className}`} dir="ltr" data-chart-interactive="true">
      <div ref={containerRef} className="h-full w-full" />
      {crosshairPoint && (
        <div className={`pointer-events-none absolute start-3 top-3 z-10 rounded-lg border px-2 py-1 text-xs font-bold backdrop-blur ${
          isDark ? 'border-white/10 bg-black/75 text-white' : 'border-black/10 bg-white/85 text-[#3B2E13]'
        }`}>
          <div>{formatPrice(crosshairPoint.value, currencyMode, language)}</div>
          <div className={`mt-0.5 text-[10px] font-medium ${isDark ? 'text-[#CDBB8C]' : 'text-[#7A5E24]'}`}>
            {formatChartDateTime(crosshairPoint.time, language)}
          </div>
        </div>
      )}
    </div>
  );
}

function AssetIcon({ id, className = '' }: { id: AssetId; className?: string }) {
  const symbols: Record<AssetId, string> = { gold: 'Au', silver: 'Ag', usdt: '₮', btc: '₿' };
  return <span className={`inline-flex items-center justify-center rounded-full bg-black/10 font-black ${className}`} dir="ltr">{symbols[id]}</span>;
}

export function DashboardView() {
  const { language, theme, currencyMode } = useAppContext();
  const isDark = theme === 'dark';
  const queryClient = useQueryClient();

  const [assetOrder, setAssetOrder] = useState<AssetId[]>(getInitialAssetOrder);
  const [timeframeByAsset, setTimeframeByAsset] = useState<Record<AssetId, PriceTimeframe>>(DEFAULT_TIMEFRAMES);
  const [socketStatus, setSocketStatus] = useState<'connecting' | 'live' | 'fallback'>('connecting');
  const [draggedAssetId, setDraggedAssetId] = useState<AssetId | null>(null);
  const [dragOverAssetId, setDragOverAssetId] = useState<AssetId | null>(null);
  const [dragReadyAssetId, setDragReadyAssetId] = useState<AssetId | null>(null);
  const [isAlertModalOpen, setIsAlertModalOpen] = useState(false);
  const [selectedAssetForAlert, setSelectedAssetForAlert] = useState<AssetId>('gold');
  const [alertTargetPrice, setAlertTargetPrice] = useState('');
  const [alertNotifyApp, setAlertNotifyApp] = useState(true);
  const [alertNotifyEmail, setAlertNotifyEmail] = useState(false);
  const [alertNotifyWebhook, setAlertNotifyWebhook] = useState(false);
  const [alertWebhookUrl, setAlertWebhookUrl] = useState('');
  const [alertEnableDlq, setAlertEnableDlq] = useState(false);
  const [isSavingAlert, setIsSavingAlert] = useState(false);
  const [fullscreenAsset, setFullscreenAsset] = useState<AssetId | null>(null);
  const [expandedSources, setExpandedSources] = useState<Partial<Record<AssetId, boolean>>>({});
  const [sourceDetails, setSourceDetails] = useState<Partial<Record<AssetId, InstrumentSourcesResponse>>>({});
  const [sourceLoading, setSourceLoading] = useState<Partial<Record<AssetId, boolean>>>({});
  const [sourceErrors, setSourceErrors] = useState<Partial<Record<AssetId, string>>>({});
  const lastWsEventsRef = useRef(new Map<string, { sequence: number | null; timestamp: number | null }>());
  const dragActivationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    window.localStorage.setItem(CHART_ORDER_STORAGE_KEY, JSON.stringify(assetOrder));
  }, [assetOrder]);

  useEffect(() => () => {
    if (dragActivationTimerRef.current) clearTimeout(dragActivationTimerRef.current);
  }, []);

  const pricesQuery = useQuery({
    queryKey: queryKeys.prices,
    queryFn: ({ signal }) => getPrices(signal),
    placeholderData: keepPreviousData,
    refetchInterval: socketStatus === 'live' ? false : 15_000,
    refetchIntervalInBackground: false,
  });

  const historyQueries = useQueries({
    queries: DEFAULT_ASSET_ORDER.map((asset) => {
      const assetTimeframe = timeframeByAsset[asset];
      return {
        queryKey: queryKeys.priceHistory(asset, assetTimeframe),
        queryFn: ({ signal }: { signal: AbortSignal }) => getPriceHistory(asset, assetTimeframe, signal),
        placeholderData: keepPreviousData,
        staleTime: assetTimeframe === '1h' || assetTimeframe === '24h' ? 30_000 : 5 * 60_000,
        refetchInterval: assetTimeframe === '1h' || assetTimeframe === '24h' ? 60_000 : 5 * 60_000,
        refetchIntervalInBackground: false,
      };
    }),
  });

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryCount = 0;
    let lastMessageAt = Date.now();
    const heartbeatTimeout = Math.max(Number(import.meta.env.VITE_WS_HEARTBEAT_TIMEOUT_MS) || 45_000, 15_000);

    const mergeMessage = (message: unknown): void => {
      if (!message || typeof message !== 'object') return;
      const root = message as Record<string, unknown>;
      if (root.type === 'heartbeat' || root.event_type === 'heartbeat') return;
      if (Array.isArray(root.prices)) {
        root.prices.forEach((price) => mergeMessage(price));
        return;
      }
      const nested = root.data ?? root.payload ?? root;
      if (!nested || typeof nested !== 'object') return;
      const payload = nested as Record<string, unknown>;
      let incoming: unknown[] = [];
      if (Array.isArray(payload.assets)) {
        incoming = payload.assets;
      } else if (typeof payload.asset === 'string') {
        incoming = [payload];
      } else if (
        typeof payload.instrument_id === 'string' &&
        (typeof payload.compatibility_asset === 'string' || typeof payload.compatibility_asset_id === 'string')
      ) {
        const instrumentId = payload.instrument_id;
        const compatibilityAsset = String(payload.compatibility_asset ?? payload.compatibility_asset_id);
        const eventKey = instrumentId;
        const sequenceValue = Number(root.sequence ?? payload.sequence ?? payload.sequence_number);
        const sequence = Number.isFinite(sequenceValue) ? sequenceValue : null;
        const timestampText = payload.canonical_at ?? payload.observed_at;
        const timestamp = typeof timestampText === 'string' && Number.isFinite(Date.parse(timestampText))
          ? Date.parse(timestampText)
          : null;
        const previous = lastWsEventsRef.current.get(eventKey);
        if (
          previous &&
          ((sequence !== null && previous.sequence !== null && sequence <= previous.sequence) ||
            (sequence === null && timestamp !== null && previous.timestamp !== null && timestamp <= previous.timestamp))
        ) {
          return;
        }
        lastWsEventsRef.current.set(eventKey, { sequence, timestamp });

        const candidate = payload.candidate && typeof payload.candidate === 'object'
          ? payload.candidate as Record<string, unknown>
          : null;
        const price = typeof payload.price === 'number' ? payload.price : null;
        const candidatePrice = candidate && typeof candidate.price === 'number'
          ? candidate.price
          : typeof payload.candidate === 'number' ? payload.candidate
          : typeof payload.candidate_price === 'number' ? payload.candidate_price : null;
        const isToman = instrumentId.includes('_TOMAN');
        const sourceValue = payload.source_summary;
        const sourceText = typeof sourceValue === 'string'
          ? sourceValue
          : sourceValue && typeof sourceValue === 'object'
            ? Object.keys(sourceValue as Record<string, unknown>).join(', ')
            : 'stored canonical';
        const status = normalizeStatus(payload.persistence_status === 'unpersisted' ? 'unpersisted' : payload.status);
        incoming = [{
          asset: compatibilityAsset,
          ...(isToman ? { price_toman: price, toman_status: status, source_toman: sourceText } : { price_usd: price, usd_status: status, source_usd: sourceText }),
          observed_at: typeof payload.observed_at === 'string' ? payload.observed_at : null,
          canonical_at: typeof payload.canonical_at === 'string' ? payload.canonical_at : null,
          age_seconds: typeof payload.age_seconds === 'number' ? payload.age_seconds : null,
          source_summary: sourceValue ?? null,
          ...(isToman ? { candidate_price_toman: candidatePrice } : { candidate_price_usd: candidatePrice }),
          candidate_provider: candidate && typeof candidate.provider_name === 'string'
            ? candidate.provider_name
            : candidate && typeof candidate.provider_id === 'string' ? candidate.provider_id : null,
          candidate_observed_at: candidate && typeof candidate.observed_at === 'string'
            ? candidate.observed_at
            : typeof payload.candidate_observed_at === 'string' ? payload.candidate_observed_at : null,
          difference_percent: candidate && typeof candidate.difference_percent === 'number'
            ? candidate.difference_percent
            : typeof payload.difference_percent === 'number' ? payload.difference_percent : null,
          verification_status: typeof payload.verification_status === 'string' ? payload.verification_status : null,
        }];
      }
      const validAssets = incoming.filter(
        (asset): asset is Record<string, unknown> => Boolean(asset && typeof asset === 'object' && typeof (asset as Record<string, unknown>).asset === 'string'),
      );
      if (validAssets.length === 0) return;

      queryClient.setQueryData<PricesResponse>(queryKeys.prices, (current) => {
        const currentAssets = current?.assets ?? EMPTY_ASSETS;
        const byId = new Map(currentAssets.map((asset) => [asset.asset, asset]));
        for (const next of validAssets) {
          const assetId = next.asset as string;
          const fallback = DEFAULT_ASSET_ORDER.includes(assetId as AssetId)
            ? buildPlaceholderAsset(assetId as AssetId)
            : undefined;
          const base = byId.get(assetId) ?? fallback;
          if (base) byId.set(assetId, { ...base, ...next } as PriceAsset);
        }
        return {
          refreshed_at: typeof payload.refreshed_at === 'string' ? payload.refreshed_at : new Date().toISOString(),
          source: payload.source && typeof payload.source === 'object'
            ? payload.source as PricesResponse['source']
            : current?.source ?? {},
          assets: [...byId.values()],
        };
      });
    };

    const connect = () => {
      if (stopped || !navigator.onLine) {
        setSocketStatus('fallback');
        return;
      }
      setSocketStatus('connecting');
      socket = new WebSocket(getPricesWebSocketUrl());
      socket.onopen = () => {
        retryCount = 0;
        lastMessageAt = Date.now();
        lastWsEventsRef.current.clear();
        setSocketStatus('live');
      };
      socket.onmessage = (event) => {
        lastMessageAt = Date.now();
        try {
          mergeMessage(JSON.parse(event.data));
        } catch {
          // A bad event does not end a healthy socket or start duplicate polling.
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (stopped) return;
        setSocketStatus('fallback');
        void queryClient.invalidateQueries({ queryKey: queryKeys.prices });
        retryCount += 1;
        const baseDelay = Math.min(1_000 * 2 ** Math.max(retryCount - 1, 0), 30_000);
        const delayWithJitter = Math.round(baseDelay * (0.8 + Math.random() * 0.4));
        retryTimer = setTimeout(connect, delayWithJitter);
      };
    };
    const reconnectWhenOnline = () => {
      if (retryTimer) clearTimeout(retryTimer);
      if (!socket || socket.readyState === WebSocket.CLOSED) connect();
    };
    const switchToPolling = () => {
      setSocketStatus('fallback');
      socket?.close();
    };

    connect();
    const watchdog = setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN && Date.now() - lastMessageAt > heartbeatTimeout) socket.close();
    }, 5_000);
    window.addEventListener('online', reconnectWhenOnline);
    window.addEventListener('offline', switchToPolling);
    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      clearInterval(watchdog);
      socket?.close();
      window.removeEventListener('online', reconnectWhenOnline);
      window.removeEventListener('offline', switchToPolling);
    };
  }, [queryClient]);

  const pricesData = pricesQuery.data?.assets ?? EMPTY_ASSETS;
  const isLoading = pricesQuery.isPending;
  const loadError = pricesQuery.error instanceof Error ? pricesQuery.error.message : null;

  const historyByAsset = useMemo(() => {
    const next: Record<AssetId, AssetPoint[]> = { gold: [], silver: [], usdt: [], btc: [] };
    DEFAULT_ASSET_ORDER.forEach((asset, index) => {
      next[asset] = historyQueries[index]?.data?.points ?? [];
    });
    return next;
  }, [historyQueries]);

  const orderedAssets = useMemo(() => {
    return assetOrder.map((id) => {
      const live = pricesData.find((a) => a.asset === id);
      const card = buildLiveCard(live, id);
      return { ...card, history: historyByAsset[id] };
    });
  }, [assetOrder, historyByAsset, pricesData]);

  useEffect(() => {
    setExpandedSources({});
    setSourceDetails({});
    setSourceErrors({});
  }, [currencyMode]);

  const toggleSourcePanel = async (assetId: AssetId) => {
    const willOpen = !expandedSources[assetId];
    setExpandedSources((current) => ({ ...current, [assetId]: willOpen }));
    if (!willOpen || sourceDetails[assetId] || sourceLoading[assetId]) return;
    setSourceLoading((current) => ({ ...current, [assetId]: true }));
    setSourceErrors((current) => ({ ...current, [assetId]: '' }));
    try {
      const details = await api.instruments.sources(INSTRUMENT_IDS[assetId][currencyMode]);
      setSourceDetails((current) => ({ ...current, [assetId]: details }));
    } catch (error) {
      setSourceErrors((current) => ({
        ...current,
        [assetId]: error instanceof Error ? error.message : 'Source data is unavailable',
      }));
    } finally {
      setSourceLoading((current) => ({ ...current, [assetId]: false }));
    }
  };

  const reorderAssets = (draggedId: AssetId, targetId: AssetId) => {
    setAssetOrder((prev) => {
      const newOrder = [...prev];
      const fromIndex = newOrder.indexOf(draggedId);
      const toIndex = newOrder.indexOf(targetId);
      newOrder.splice(fromIndex, 1);
      newOrder.splice(toIndex, 0, draggedId);
      return newOrder;
    });
  };

  const clearDragActivation = () => {
    if (!dragActivationTimerRef.current) return;
    clearTimeout(dragActivationTimerRef.current);
    dragActivationTimerRef.current = null;
  };

  const armCardDrag = (assetId: AssetId, target: EventTarget | null) => {
    const element = target instanceof Element ? target : null;
    if (element?.closest('button, a, input, textarea, select, [data-chart-interactive="true"]')) return;
    clearDragActivation();
    setDragReadyAssetId(null);
    dragActivationTimerRef.current = setTimeout(() => {
      setDragReadyAssetId(assetId);
      dragActivationTimerRef.current = null;
    }, 450);
  };

  const currentUsdt = orderedAssets.find((a) => a.id === 'usdt');
  // Derive the USD→Toman rate from Tether only when both legs are present and
  // non-zero. Falling back to 1 would silently render USD figures as Toman.
  const usdToTomanRate =
    currentUsdt?.priceToman && currentUsdt?.priceUsd
      ? currentUsdt.priceToman / currentUsdt.priceUsd
      : null;

  const t = {
    usd: { fa: 'دلار', en: 'USD' },
    toman: { fa: 'تومان', en: 'Toman' },
    createAlert: { fa: 'ایجاد هشدار', en: 'Create Alert' },
    alertFor: { fa: 'هشدار برای', en: 'Alert for' },
    targetPrice: { fa: 'قیمت هدف', en: 'Target Price' },
    notifyVia: { fa: 'اطلاع‌رسانی از طریق', en: 'Notify via' },
    appAlert: { fa: 'اعلان برنامه', en: 'App Notification' },
    emailAlert: { fa: 'ایمیل', en: 'Email' },
    cancel: { fa: 'انصراف', en: 'Cancel' },
    save: { fa: 'ذخیره', en: 'Save Alert' },
    alertSuccess: { fa: 'هشدار با موفقیت ثبت شد', en: 'Alert created successfully' },
    retry: { fa: 'تلاش دوباره', en: 'Retry' },
  };

  const activeCurrencyLabel = currencyMode === 'usd' ? t.usd[language] : t.toman[language];

  const statusLabels: Record<OperationalPriceStatus, { fa: string; en: string }> = {
    live: { fa: 'زنده', en: 'Live' },
    fresh_cache: { fa: 'ذخیره تازه', en: 'Fresh cache' },
    cached: { fa: 'ذخیره تازه', en: 'Fresh cache' },
    verifying: { fa: 'در حال بررسی', en: 'Verifying' },
    suspicious: { fa: 'مشکوک', en: 'Suspicious' },
    suspicious_unconfirmed: { fa: 'تأیید نشده', en: 'Unconfirmed' },
    derived_fallback: { fa: 'قیمت محاسبه‌شده', en: 'Derived fallback' },
    stale: { fa: 'قدیمی', en: 'Stale' },
    expired: { fa: 'منقضی', en: 'Expired' },
    unpersisted: { fa: 'ذخیره‌نشده', en: 'Unpersisted' },
    unavailable: { fa: 'خارج از دسترس', en: 'Unavailable' },
  };

  const statusLabel = (status: OperationalPriceStatus) => statusLabels[status]?.[language] ?? status;

  const healthyStatuses = new Set<OperationalPriceStatus>(['live', 'fresh_cache', 'cached']);
  const hasDegradedSources = !pricesQuery.isPending && orderedAssets.some(
    (asset) => !healthyStatuses.has(asset.usdStatus) || !healthyStatuses.has(asset.tomanStatus)
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent('pricing-health', {
        detail: { degraded: hasDegradedSources },
      }));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [hasDegradedSources]);

  return (
    <div className="flex flex-col gap-4">

      {loadError && (
        <div className={`flex items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-xs font-medium ${isDark ? 'border-red-500/20 bg-red-500/5 text-red-400' : 'border-red-300 bg-red-50 text-red-700'}`}>
          <span>{language === 'fa' ? `خطا در دریافت قیمت‌ها: ${loadError}` : `Failed to load prices: ${loadError}`}</span>
          <button type="button" onClick={() => pricesQuery.refetch()} className="shrink-0 rounded-lg border border-current px-2 py-1 font-bold">
            {t.retry[language]}
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {orderedAssets.map((asset, idx) => {
        const assetTimeframe = timeframeByAsset[asset.id];
        const fallbackValue = currencyMode === 'usd'
          ? (asset.priceUsd ?? (asset.priceToman && usdToTomanRate ? asset.priceToman / usdToTomanRate : null))
          : (asset.priceToman ?? (asset.priceUsd && usdToTomanRate ? asset.priceUsd * usdToTomanRate : null));
        const activeStatus = currencyMode === 'usd' ? asset.usdStatus : asset.tomanStatus;
        const candidatePrice = currencyMode === 'usd' ? asset.candidatePriceUsd : asset.candidatePriceToman;
        const isAnomaly = activeStatus === 'verifying' || activeStatus === 'suspicious' || activeStatus === 'suspicious_unconfirmed';
        const sourceRows = [...(sourceDetails[asset.id]?.sources ?? [])].sort((left, right) => {
          const roleRank: Record<string, number> = { primary: 0, verifier: 1, fallback: 2, derived: 3 };
          const leftStale = left.status === 'stale' || left.status === 'expired' || left.status === 'rejected' ? 10 : 0;
          const rightStale = right.status === 'stale' || right.status === 'expired' || right.status === 'rejected' ? 10 : 0;
          return leftStale + (roleRank[left.role ?? ''] ?? 4) - rightStale - (roleRank[right.role ?? ''] ?? 4);
        });

        const safeHistory = Array.isArray(asset.history) ? asset.history : [];
        const resolvedHistory = safeHistory.length > 0 ? [...safeHistory] : [
          { timestamp: new Date().toISOString(), value_usd: asset.priceUsd, value_toman: asset.priceToman }
        ];

        const chartData = toChartData(resolvedHistory, currencyMode, usdToTomanRate);
        const chartColor = isDark ? CHART_COLORS[asset.id].dark : CHART_COLORS[asset.id].light;

        const chartErrorMsg = typeof asset.chartErrorMessage === 'string' 
            ? asset.chartErrorMessage 
            : (asset.chartErrorMessage?.[language] || 'امکان دریافت اطلاعات نمودار وجود ندارد');

        const showChartError = asset.chartError && safeHistory.length === 0 && asset.priceUsd === null && asset.priceToman === null;

        return (
          <motion.div
            key={asset.id}
            layoutId={asset.id}
            draggable
            title={language === 'fa' ? 'برای جابه‌جایی کارت را نگه دارید و بکشید' : 'Hold, then drag to reorder'}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0, scale: dragOverAssetId === asset.id ? 1.02 : 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{
              delay: idx * 0.05,
              duration: 0.35,
              ease: [0.22, 1, 0.36, 1],
              layout: { type: 'spring', damping: 28, stiffness: 330 }
            }}
            onPointerDown={(event) => armCardDrag(asset.id, event.target)}
            onPointerUp={() => {
              clearDragActivation();
              setDragReadyAssetId(null);
            }}
            onPointerCancel={() => {
              clearDragActivation();
              setDragReadyAssetId(null);
            }}
            onDragStartCapture={(event) => {
              if (dragReadyAssetId !== asset.id) {
                event.preventDefault();
                return;
              }
              event.dataTransfer.effectAllowed = 'move';
              setDraggedAssetId(asset.id);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragEnter={() => {
              if (draggedAssetId && draggedAssetId !== asset.id) {
                setDragOverAssetId(asset.id);
              }
            }}
            onDrop={() => {
              if (draggedAssetId) {
                reorderAssets(draggedAssetId, asset.id);
                setDraggedAssetId(null);
                setDragOverAssetId(null);
                setDragReadyAssetId(null);
              }
            }}
            onDragEndCapture={() => {
              setDraggedAssetId(null);
              setDragOverAssetId(null);
              setDragReadyAssetId(null);
            }}
          >
            <Card
              className={`relative overflow-hidden rounded-[2.5rem] backdrop-blur-2xl transition-all duration-500 ${
                isDark 
                  ? 'border-white/5 bg-[#0E0E0E]/60 shadow-xl' 
                  : 'border-black/5 bg-white/60 shadow-xl'
              } ${
                dragOverAssetId === asset.id 
                  ? 'ring-2 ring-[#D4AF37]/50 shadow-[0_0_30px_rgba(212,175,55,0.3)] scale-[1.02]' 
                  : dragReadyAssetId === asset.id
                    ? 'ring-1 ring-[#D4AF37]/40 cursor-grabbing'
                    : 'cursor-grab'
              } hover:shadow-[0_8px_32px_rgba(212,175,55,0.15)] hover:-translate-y-1`}
            >
              <CardHeader className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-2">
                  <div>
                    <CardTitle className={`flex items-center gap-2 text-lg font-semibold ${isDark ? 'text-[#E8D9AE]' : 'text-[#6A4D16]'}`}>
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl text-[#111111]" style={{ backgroundColor: chartColor }}>
                        <AssetIcon id={asset.id} className="h-7 w-7 text-[11px]" />
                      </div>
                      {asset.label[language]}
                    </CardTitle>

                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                      <span
                        className={`rounded-full px-2 py-0.5 font-semibold ${
                          isDark ? STATUS_COLORS[asset.usdStatus].dark : STATUS_COLORS[asset.usdStatus].light
                        }`}
                        title={`USD: ${asset.sourceUsd}`}
                      >
                        USD {statusLabel(asset.usdStatus)}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 font-semibold ${
                          isDark ? STATUS_COLORS[asset.tomanStatus].dark : STATUS_COLORS[asset.tomanStatus].light
                        }`}
                        title={`Toman: ${asset.sourceToman}`}
                      >
                        Toman {statusLabel(asset.tomanStatus)}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className={`flex items-center gap-1 rounded-2xl px-3 py-1.5 text-xs font-semibold backdrop-blur-md ${
                    !Number.isFinite(asset.changePercent)
                      ? isDark ? 'bg-white/5 text-[#CDBB8C]' : 'bg-black/5 text-[#7A5E24]'
                      : asset.isUp
                        ? isDark ? 'bg-emerald-500/20 text-emerald-400' : 'bg-emerald-100 text-emerald-700'
                        : isDark ? 'bg-red-500/20 text-red-400' : 'bg-red-100 text-red-700'
                  }`}>
                    {Number.isFinite(asset.changePercent) && (asset.isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />)}
                    <span dir="ltr">{Number.isFinite(asset.changePercent) ? `${Math.abs(asset.changePercent).toFixed(2)}%` : '0%'}</span>
                  </div>
                  <Button
                    onClick={() => {
                      setSelectedAssetForAlert(asset.id);
                      setIsAlertModalOpen(true);
                    }}
                    variant="outline"
                    size="icon"
                    className={`h-10 w-10 rounded-xl transition-all ${
                      isDark 
                        ? 'border-white/10 text-[#D4AF37] hover:bg-white/5 hover:text-[#F3E2AB]' 
                        : 'border-black/10 text-[#8A6A23] hover:bg-black/5 hover:text-[#5E4714]'
                    }`}
                  >
                    <BellPlus size={18} />
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="mb-6 flex items-baseline gap-2">
                  <div className={`text-4xl font-bold tracking-tight ${isDark ? 'text-white' : 'text-[#3B2E13]'}`} dir="ltr">
                    {formatPrice(fallbackValue, currencyMode, language)}
                  </div>
                  <span className={`text-sm font-medium ${isDark ? 'text-[#CDBB8C]' : 'text-[#8A6B26]'}`}>
                    {activeCurrencyLabel}
                  </span>
                </div>

                <div className={`mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2 text-xs ${
                  isDark ? 'border-white/5 bg-black/20 text-[#A89668]' : 'border-black/5 bg-white/50 text-[#7A5E24]'
                }`}>
                  <div className="flex min-w-0 flex-wrap items-center gap-3">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 font-semibold ${
                      isDark ? STATUS_COLORS[activeStatus].dark : STATUS_COLORS[activeStatus].light
                    }`}>
                      <Database size={12} /> {statusLabel(activeStatus)}
                    </span>
                    {(asset.canonicalAt || asset.observedAt) && (
                      <span dir="ltr">
                        {new Date(asset.canonicalAt ?? asset.observedAt ?? '').toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => void toggleSourcePanel(asset.id)}
                    className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 font-bold transition ${
                      isAnomaly
                        ? 'border-orange-400/50 bg-orange-500/10 text-orange-400'
                        : isDark ? 'border-white/10 text-[#D4AF37] hover:bg-white/5' : 'border-black/10 text-[#8A6A23] hover:bg-black/5'
                    }`}
                  >
                    {language === 'fa' ? 'مقایسه منابع' : 'Compare sources'}
                    <ChevronDown size={13} className={`transition-transform ${expandedSources[asset.id] ? 'rotate-180' : ''}`} />
                  </button>
                </div>

                {isAnomaly && candidatePrice !== null && (
                  <div className={`mb-4 rounded-xl border px-3 py-3 text-xs ${
                    isDark ? 'border-orange-500/30 bg-orange-500/5 text-orange-200' : 'border-orange-300 bg-orange-50 text-orange-800'
                  }`}>
                    <div className="mb-1 flex items-center gap-2 font-bold">
                      <AlertTriangle size={14} />
                      {language === 'fa' ? 'قیمت مشکوک؛ قیمت پذیرفته‌شده هنوز نمایش داده می‌شود.' : 'Suspicious candidate; the last accepted price remains primary.'}
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1" dir="ltr">
                      <span>{formatPrice(candidatePrice, currencyMode, language)} {activeCurrencyLabel}</span>
                      {asset.candidateProvider && <span>{asset.candidateProvider}</span>}
                      {asset.candidateObservedAt && <span>{new Date(asset.candidateObservedAt).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</span>}
                      {asset.differencePercent !== null && <span>{asset.differencePercent.toFixed(2)}%</span>}
                      {asset.verificationStatus && <span>{asset.verificationStatus}</span>}
                    </div>
                  </div>
                )}

                <AnimatePresence initial={false}>
                  {expandedSources[asset.id] && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      className={`mb-4 overflow-hidden rounded-xl border ${isDark ? 'border-white/5 bg-black/20' : 'border-black/5 bg-white/60'}`}
                    >
                      {sourceLoading[asset.id] ? (
                        <div className={`p-4 text-center text-xs ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>
                          {language === 'fa' ? 'در حال دریافت داده ذخیره‌شده...' : 'Loading stored source data...'}
                        </div>
                      ) : sourceErrors[asset.id] ? (
                        <div className="p-4 text-center text-xs text-red-400">{sourceErrors[asset.id]}</div>
                      ) : sourceRows.length === 0 ? (
                        <div className={`p-4 text-center text-xs ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>
                          {language === 'fa' ? 'داده منبعی ذخیره نشده است.' : 'No stored source quotes.'}
                        </div>
                      ) : (
                        <div className="divide-y divide-white/5">
                          {sourceRows.map((source, sourceIndex) => {
                            const rowStatus = normalizeStatus(source.status);
                            const isOld = source.status === 'stale' || source.status === 'expired' || source.status === 'rejected';
                            return (
                              <div key={String(source.id ?? `${source.provider_id ?? 'source'}-${sourceIndex}`)} className={`grid grid-cols-[1fr_auto] gap-3 px-3 py-2.5 text-xs ${isOld ? 'opacity-55 grayscale' : ''}`}>
                                <div className="min-w-0">
                                  <div className={`truncate font-bold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>
                                    {source.provider_name ?? source.provider_id ?? (language === 'fa' ? 'منبع' : 'Source')}
                                  </div>
                                  <div className={`mt-0.5 flex flex-wrap gap-2 ${isDark ? 'text-[#887850]' : 'text-[#8A6A25]'}`}>
                                    <span>{source.role ?? 'source'}</span>
                                    <span>{statusLabel(rowStatus)}</span>
                                    <span>{formatAge(source.age_seconds ?? null, language)}</span>
                                    {source.observed_at && <span dir="ltr">{new Date(source.observed_at).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</span>}
                                    {source.rejection_reason && <span>{source.rejection_reason}</span>}
                                  </div>
                                </div>
                                <div className="text-end font-bold" dir="ltr">
                                  <div className={isDark ? 'text-white' : 'text-[#3B2E13]'}>{formatPrice(source.price, currencyMode, language)}</div>
                                  {source.difference_percent !== null && source.difference_percent !== undefined && (
                                    <div className="text-[10px] text-[#D4AF37]">{source.difference_percent.toFixed(2)}%</div>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
                  <div className={`flex rounded-xl p-1 ${isDark ? 'bg-black/40' : 'bg-[#F6EBD0]'}`} dir="ltr">
                    {TIMEFRAMES.map((value) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setTimeframeByAsset((current) => ({
                          ...current,
                          [asset.id]: value,
                        }))}
                        className={`min-w-10 rounded-lg px-2 py-1.5 text-[11px] font-bold transition sm:min-w-12 sm:text-xs ${
                          assetTimeframe === value
                            ? 'bg-[#D4AF37] text-black shadow-sm'
                            : isDark ? 'text-[#A89668] hover:text-white' : 'text-[#7A5E24] hover:text-[#3B2E13]'
                        }`}
                      >
                        {value}
                      </button>
                    ))}
                  </div>
                </div>

                {showChartError ? (
                  <div className={`flex h-[400px] min-h-[400px] w-full flex-col items-center justify-center rounded-[1.5rem] border backdrop-blur-md ${
                    isDark ? 'border-red-500/20 bg-[#1A0B0B]/50' : 'border-red-200 bg-[#FFF0F0]/50'
                  }`}>
                    <div className={`text-sm font-semibold ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                      {chartErrorMsg}
                    </div>
                  </div>
                ) : (
                  <>
                    <div
                      className="relative"
                    >
                      <button
                        onClick={() => setFullscreenAsset(asset.id)}
                        className={`absolute top-2 right-2 z-10 flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${isDark ? 'bg-[#1A1A1A]/80 text-[#D4AF37] hover:bg-[#222222]' : 'bg-white/80 text-[#8A6B20] hover:bg-white'} backdrop-blur-sm`}
                        title={language === 'fa' ? 'تمام صفحه' : 'Full Screen'}
                      >
                        <Maximize2 size={16} />
                      </button>
                      {isLoading ? (
                        <div className={`h-[400px] min-h-[400px] w-full animate-pulse rounded-[1.5rem] ${isDark ? 'bg-white/5' : 'bg-black/5'}`} />
                      ) : (
                        <FinancialChart
                          data={chartData}
                          color={chartColor}
                          isDark={isDark}
                          currencyMode={currencyMode}
                          language={language}
                          className={`h-[400px] min-h-[400px] rounded-[1.5rem] border p-2 backdrop-blur-md transition-colors ${
                        isDark 
                          ? 'border-white/5 bg-[#111111]/40' 
                          : 'border-black/5 bg-white/40'
                          }`}
                        />
                      )}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </motion.div>
        );
      })}</div>

      <Modal isOpen={isAlertModalOpen} onClose={() => setIsAlertModalOpen(false)} title={t.createAlert[language]} size="large">
        <div className="space-y-6 pt-4 max-h-[70vh] overflow-y-auto px-1">
          <div className="space-y-2">
            <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
              {t.alertFor[language]}
            </label>
            <div className={`flex items-center gap-3 rounded-[1.5rem] border p-3 ${isDark ? 'border-[#D4AF37]/20 bg-[#111111]' : 'border-[#D4AF37]/35 bg-[#FFF0CC]'}`}>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#D4AF37] text-[#0A0A0A]">
                <AssetIcon id={selectedAssetForAlert} className="h-7 w-7 text-[11px]" />
              </div>
              <span className={`font-bold ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                {ASSET_LABELS[selectedAssetForAlert][language]}
              </span>
            </div>
          </div>

          <div className="space-y-2">
            <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
              {t.targetPrice[language]} ({activeCurrencyLabel})
            </label>
            <Input
              type="number"
              dir="ltr"
              placeholder="0.00"
              step="0.01"
              value={alertTargetPrice}
              onChange={(e) => setAlertTargetPrice(e.target.value)}
              className={`h-14 rounded-2xl text-lg font-bold tracking-wider ${
                isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3]' : 'border-[#D4AF37]/30 bg-white text-[#3B2E13]'
              }`}
            />
          </div>

          <div className="space-y-4 pt-2">
            <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
              {t.notifyVia[language]}
            </label>
            <div className="space-y-4">
              <div className={`flex items-start gap-3 rounded-xl border p-4 transition-colors ${isDark ? 'border-[#D4AF37]/20 bg-[#0F0F0F] hover:bg-[#141414]' : 'border-[#D4AF37]/30 bg-[#FFFBF0] hover:bg-white'}`}>
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${isDark ? 'bg-blue-500/10 text-blue-400' : 'bg-blue-100 text-blue-700'}`}>
                  <Smartphone size={18} />
                </div>
                <div className="flex-1">
                  <div className={`font-semibold text-sm mb-1 ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>{t.appAlert[language]}</div>
                  <p className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                    {language === 'fa' ? 'اعلان فوری در اپلیکیشن' : 'Instant in-app notification'}
                  </p>
                </div>
                <Switch checked={alertNotifyApp} onCheckedChange={setAlertNotifyApp} />
              </div>

              <div className={`flex items-start gap-3 rounded-xl border p-4 transition-colors ${isDark ? 'border-[#D4AF37]/20 bg-[#0F0F0F] hover:bg-[#141414]' : 'border-[#D4AF37]/30 bg-[#FFFBF0] hover:bg-white'}`}>
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${isDark ? 'bg-emerald-500/10 text-emerald-400' : 'bg-emerald-100 text-emerald-700'}`}>
                  <Mail size={18} />
                </div>
                <div className="flex-1 space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className={`font-semibold text-sm mb-1 ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>{t.emailAlert[language]}</div>
                      <p className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                        {language === 'fa' ? 'ارسال به ایمیل ثبت‌شده' : 'Send to registered email'}
                      </p>
                    </div>
                    <Switch checked={alertNotifyEmail} onCheckedChange={setAlertNotifyEmail} />
                  </div>
                </div>
              </div>

              <div className={`flex items-start gap-3 rounded-xl border p-4 transition-colors ${isDark ? 'border-[#D4AF37]/20 bg-[#0F0F0F] hover:bg-[#141414]' : 'border-[#D4AF37]/30 bg-[#FFFBF0] hover:bg-white'}`}>
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${isDark ? 'bg-purple-500/10 text-purple-400' : 'bg-purple-100 text-purple-700'}`}>
                  <Webhook size={18} />
                </div>
                <div className="flex-1 space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className={`font-semibold text-sm mb-1 ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                        {language === 'fa' ? 'وب‌هوک' : 'Webhook'}
                      </div>
                      <p className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                        {language === 'fa' ? 'ارسال به آدرس API سفارشی' : 'Send to custom API endpoint'}
                      </p>
                    </div>
                    <Switch checked={alertNotifyWebhook} onCheckedChange={setAlertNotifyWebhook} />
                  </div>
                  {alertNotifyWebhook && (
                    <Input
                      type="url"
                      placeholder="https://api.example.com/webhook"
                      value={alertWebhookUrl}
                      onChange={(e) => setAlertWebhookUrl(e.target.value)}
                      className={`h-10 text-xs ${isDark ? 'bg-[#0A0A0A] border-[#D4AF37]/10' : 'bg-white border-[#D4AF37]/20'}`}
                      dir="ltr"
                    />
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-3 pt-2">
            <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
              {language === 'fa' ? 'صف ناموفق‌ها (DLQ)' : 'Dead Letter Queue'}
            </label>
            <div className={`rounded-xl border p-4 ${isDark ? 'border-amber-500/20 bg-amber-500/5' : 'border-amber-300 bg-amber-50'}`}>
              <div className="flex items-start gap-3">
                <AlertTriangle size={18} className={isDark ? 'text-amber-400 mt-0.5' : 'text-amber-600 mt-0.5'} />
                <div className="flex-1">
                  <div className={`text-xs font-medium mb-1 ${isDark ? 'text-amber-300' : 'text-amber-800'}`}>
                    {language === 'fa' ? 'هشدارهای ارسال‌نشده' : 'Failed Delivery Alerts'}
                  </div>
                  <p className={`text-xs ${isDark ? 'text-amber-400/70' : 'text-amber-700/70'}`}>
                    {language === 'fa'
                      ? 'هشدارهایی که به دلیل خطا ارسال نشدند، در صف نگهداری می‌شوند و مجدداً تلاش می‌شود.'
                      : 'Alerts that fail to deliver will be queued and retried automatically.'}
                  </p>
                </div>
                <Switch checked={alertEnableDlq} onCheckedChange={setAlertEnableDlq} />
              </div>
            </div>
          </div>

          <div className="flex gap-3 pt-4">
            <Button
              variant="outline"
              className="h-12 flex-1 rounded-2xl border-[#D4AF37]/20"
              onClick={() => setIsAlertModalOpen(false)}
            >
              {t.cancel[language]}
            </Button>
            <Button
              disabled={isSavingAlert || !alertTargetPrice}
              className={`h-12 flex-1 rounded-2xl border-0 text-black shadow-lg hover:shadow-xl transition-all disabled:opacity-50 ${
                isDark ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB]' : 'bg-[#D4AF37] hover:bg-[#E8C45A]'
              }`}
              onClick={async () => {
                const price = parseFloat(alertTargetPrice);
                if (!price || isNaN(price)) return;
                setIsSavingAlert(true);
                try {
                  await api.alerts.create({
                    asset: selectedAssetForAlert,
                    target_price: price,
                    currency_mode: currencyMode,
                    condition: 'above',
                    notify_app: alertNotifyApp,
                    notify_email: alertNotifyEmail,
                    notify_webhook: alertNotifyWebhook,
                    webhook_url: alertNotifyWebhook && alertWebhookUrl ? alertWebhookUrl : null,
                    enable_dlq: alertEnableDlq,
                  });
                  toast.success(t.alertSuccess[language]);
                  setIsAlertModalOpen(false);
                  setAlertTargetPrice('');
                } catch {
                  toast.error(language === 'fa' ? 'خطا در ثبت هشدار' : 'Failed to save alert');
                } finally {
                  setIsSavingAlert(false);
                }
              }}
            >
              {isSavingAlert ? (language === 'fa' ? 'در حال ذخیره...' : 'Saving...') : t.save[language]}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal 
        isOpen={fullscreenAsset !== null} 
        onClose={() => setFullscreenAsset(null)} 
        title={fullscreenAsset ? ASSET_LABELS[fullscreenAsset][language] : ''} 
        size="large"
      >
        {fullscreenAsset && (() => {
          const asset = orderedAssets.find(a => a.id === fullscreenAsset);
          if (!asset) return null;
          
          const safeHistory = Array.isArray(asset.history) ? asset.history : [];
          const resolvedHistory = safeHistory.length > 0 ? [...safeHistory] : [
            { timestamp: new Date().toISOString(), value_usd: asset.priceUsd, value_toman: asset.priceToman }
          ];
          const chartData = toChartData(resolvedHistory, currencyMode, usdToTomanRate);
          
          const chartColor = CHART_COLORS[asset.id][isDark ? 'dark' : 'light'];
          
          return (
            <div className="space-y-4">
              <div className={`text-center text-4xl font-bold ${isDark ? 'text-[#D4AF37]' : 'text-[#8A6B20]'}`}>
                {formatPrice(currencyMode === 'usd' ? asset.priceUsd : asset.priceToman, currencyMode, language)}
              </div>
              <FinancialChart
                data={chartData}
                color={chartColor}
                isDark={isDark}
                currencyMode={currencyMode}
                language={language}
                className={`h-[60vh] rounded-2xl border p-4 ${isDark ? 'border-white/5 bg-[#111111]/40' : 'border-black/5 bg-white/40'}`}
              />
            </div>
          );
        })()}
      </Modal>
    </div>
  );
}
