import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { LineChart, Line, ResponsiveContainer, YAxis, XAxis, CartesianGrid, ReferenceLine } from 'recharts';
import { AlertTriangle, BellPlus, ArrowUpRight, ArrowDownRight, Gem, Coins, GripVertical, Bitcoin, CircleDollarSign, ChevronDown, Clock3, Radio, WifiOff } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { useAppContext } from '../context/AppContext';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { toast } from 'sonner';
import { api, formatPrice, getPriceHistory, getPrices, getPricesWebSocketUrl, type CurrencyMode, type InstrumentSourcesResponse, type OperationalPriceStatus, type PriceAsset, type PriceTimeframe } from '../services/api';

type AssetId = 'gold' | 'silver' | 'usdt' | 'btc';

type AssetPoint = {
  timestamp: string;
  value_usd: number | null;
  value_toman: number | null;
};

type AssetCard = {
  id: AssetId;
  label: { fa: string; en: string };
  icon: LucideIcon;
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
  candidatePriceUsd: number | null;
  candidatePriceToman: number | null;
  candidateProvider: string | null;
  candidateObservedAt: string | null;
  differencePercent: number | null;
  verificationStatus: string | null;
};

type TooltipPosition = {
  x: number;
  y: number;
};

const CHART_ORDER_STORAGE_KEY = 'dashboard-chart-order-v3';
const DEFAULT_ASSET_ORDER: AssetId[] = ['gold', 'silver', 'usdt', 'btc'];

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

const TIMEFRAMES: PriceTimeframe[] = ['1h', '24h', '7d', '30d', '1y'];

const ASSET_ICONS: Record<AssetId, LucideIcon> = {
  gold: Gem,
  silver: Coins,
  usdt: CircleDollarSign,
  btc: Bitcoin
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
  history: []
});

const EMPTY_ASSETS: PriceAsset[] = DEFAULT_ASSET_ORDER.map(buildPlaceholderAsset);

const normalizeStatus = (value: unknown): OperationalPriceStatus => {
  if (value === 'confirmed') return 'live';
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(STATUS_COLORS, value)
    ? value as OperationalPriceStatus
    : 'unavailable';
};

const buildLiveCard = (asset: PriceAsset | undefined, id: AssetId, icon: LucideIcon): AssetCard => {
  if (!asset) {
    const placeholder = buildPlaceholderAsset(id);
    return {
      id,
      label: { fa: placeholder.label_fa, en: placeholder.label_en },
      icon,
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
    icon,
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
    candidatePriceUsd: asset.candidate_price_usd ?? null,
    candidatePriceToman: asset.candidate_price_toman ?? null,
    candidateProvider: asset.candidate_provider ?? null,
    candidateObservedAt: asset.candidate_observed_at ?? null,
    differencePercent: asset.difference_percent ?? null,
    verificationStatus: asset.verification_status ?? null,
  };
};

const toChartValue = (point: AssetPoint, mode: CurrencyMode, fallbackValue: number | null) => {
  const raw = mode === 'usd' ? point.value_usd : point.value_toman;
  return raw ?? fallbackValue;
};

const formatAge = (seconds: number | null, language: 'fa' | 'en') => {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return language === 'fa' ? 'نامشخص' : 'Unknown';
  const value = Math.floor(seconds);
  if (value < 60) return language === 'fa' ? `${value} ثانیه` : `${value}s`;
  if (value < 3600) return language === 'fa' ? `${Math.floor(value / 60)} دقیقه` : `${Math.floor(value / 60)}m`;
  if (value < 86400) return language === 'fa' ? `${Math.floor(value / 3600)} ساعت` : `${Math.floor(value / 3600)}h`;
  return language === 'fa' ? `${Math.floor(value / 86400)} روز` : `${Math.floor(value / 86400)}d`;
};

export function DashboardView() {
  const { language, theme, currencyMode, setCurrencyMode } = useAppContext();
  const isDark = theme === 'dark';

  const [assetOrder, setAssetOrder] = useState<AssetId[]>(getInitialAssetOrder);
  const [draggedAssetId, setDraggedAssetId] = useState<AssetId | null>(null);
  const [dragOverAssetId, setDragOverAssetId] = useState<AssetId | null>(null);
  const [isAlertModalOpen, setIsAlertModalOpen] = useState(false);
  const [selectedAssetForAlert, setSelectedAssetForAlert] = useState<AssetId>('gold');
  const [alertTarget, setAlertTarget] = useState('');
  const [alertNotifyApp, setAlertNotifyApp] = useState(true);
  const [alertNotifyEmail, setAlertNotifyEmail] = useState(false);
  const [isSavingAlert, setIsSavingAlert] = useState(false);
  const [timeframe, setTimeframe] = useState<PriceTimeframe>('24h');
  const [socketStatus, setSocketStatus] = useState<'connecting' | 'live' | 'fallback'>('connecting');
  const [expandedSources, setExpandedSources] = useState<Partial<Record<AssetId, boolean>>>({});
  const [sourceDetails, setSourceDetails] = useState<Partial<Record<AssetId, InstrumentSourcesResponse>>>({});
  const [sourceLoading, setSourceLoading] = useState<Partial<Record<AssetId, boolean>>>({});
  const [sourceErrors, setSourceErrors] = useState<Partial<Record<AssetId, string>>>({});
  const lastEventsRef = useRef(new Map<string, { sequence: number | null; timestamp: number | null }>());

  const [pricesData, setPricesData] = useState<PriceAsset[]>(EMPTY_ASSETS);
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);
  const [sourceLabel, setSourceLabel] = useState<{ usd: string; toman: string }>({ usd: '...', toman: '...' });
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [activePointIndexByAsset, setActivePointIndexByAsset] = useState<Record<string, number>>({});
  const [isScrubbingByAsset, setIsScrubbingByAsset] = useState<Record<string, boolean>>({});
  const [tooltipPositionByAsset, setTooltipPositionByAsset] = useState<Record<string, TooltipPosition>>({});

  useEffect(() => {
    window.localStorage.setItem(CHART_ORDER_STORAGE_KEY, JSON.stringify(assetOrder));
  }, [assetOrder]);

  const loadPrices = useCallback(async () => {
    try {
      setLoadError(null);
      const data = await getPrices();
      setPricesData((current) => data.assets.map((item) => {
        const previous = current.find((value) => value.asset === item.asset);
        return previous?.history?.length ? { ...item, history: previous.history } : item;
      }));
      setLastRefreshAt(data.refreshed_at);
      setSourceLabel({ usd: data.source?.usd ?? 'Unknown', toman: data.source?.toman ?? 'Unknown' });
    } catch (err: any) {
      setLoadError(err.message || 'Failed to sync prices');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPrices();
    if (socketStatus === 'live') return;
    const interval = setInterval(() => void loadPrices(), 15_000);
    return () => clearInterval(interval);
  }, [loadPrices, socketStatus]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all(DEFAULT_ASSET_ORDER.map(async (asset) => ({
      asset,
      history: await getPriceHistory(asset, timeframe, controller.signal),
    })))
      .then((results) => {
        setPricesData((current) => current.map((item) => {
          const result = results.find((entry) => entry.asset === item.asset);
          return result ? { ...item, history: result.history.points } : item;
        }));
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : 'Failed to load history');
      });
    return () => controller.abort();
  }, [timeframe]);

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryCount = 0;
    let lastMessageAt = Date.now();
    const heartbeatTimeout = Math.max(Number(import.meta.env.VITE_WS_HEARTBEAT_TIMEOUT_MS) || 45_000, 15_000);

    const mergeEvent = (message: unknown): void => {
      if (!message || typeof message !== 'object') return;
      const root = message as Record<string, unknown>;
      if (root.type === 'heartbeat' || root.event_type === 'heartbeat') return;
      if (Array.isArray(root.prices)) {
        root.prices.forEach((price) => mergeEvent(price));
        return;
      }
      const raw = root.data ?? root.payload ?? root;
      if (!raw || typeof raw !== 'object') return;
      const payload = raw as Record<string, unknown>;
      if (Array.isArray(payload.assets)) {
        setPricesData((current) => {
          const byId = new Map(current.map((item) => [item.asset, item]));
          for (const value of payload.assets as Array<Record<string, unknown>>) {
            if (typeof value?.asset === 'string' && byId.has(value.asset)) byId.set(value.asset, { ...byId.get(value.asset)!, ...value } as PriceAsset);
          }
          return [...byId.values()];
        });
        return;
      }
      if (
        typeof payload.instrument_id !== 'string' ||
        (typeof payload.compatibility_asset !== 'string' && typeof payload.compatibility_asset_id !== 'string')
      ) return;
      const instrumentId = payload.instrument_id;
      const assetId = String(payload.compatibility_asset ?? payload.compatibility_asset_id);
      if (!DEFAULT_ASSET_ORDER.includes(assetId as AssetId)) return;
      const sequenceValue = Number(root.sequence ?? payload.sequence ?? payload.sequence_number);
      const sequence = Number.isFinite(sequenceValue) ? sequenceValue : null;
      const timestampValue = payload.canonical_at ?? payload.observed_at;
      const timestamp = typeof timestampValue === 'string' && Number.isFinite(Date.parse(timestampValue)) ? Date.parse(timestampValue) : null;
      const previous = lastEventsRef.current.get(instrumentId);
      if (previous && ((sequence !== null && previous.sequence !== null && sequence <= previous.sequence) || (sequence === null && timestamp !== null && previous.timestamp !== null && timestamp <= previous.timestamp))) return;
      lastEventsRef.current.set(instrumentId, { sequence, timestamp });

      const candidate = payload.candidate && typeof payload.candidate === 'object' ? payload.candidate as Record<string, unknown> : null;
      const candidatePrice = candidate && typeof candidate.price === 'number' ? candidate.price : typeof payload.candidate === 'number' ? payload.candidate : null;
      const isToman = instrumentId.includes('_TOMAN');
      const status = normalizeStatus(payload.persistence_status === 'unpersisted' ? 'unpersisted' : payload.status);
      const source = typeof payload.source_summary === 'string' ? payload.source_summary : 'stored canonical';
      setPricesData((current) => current.map((item) => item.asset !== assetId ? item : ({
        ...item,
        ...(isToman
          ? { price_toman: typeof payload.price === 'number' ? payload.price : item.price_toman, toman_status: status, source_toman: source, candidate_price_toman: candidatePrice }
          : { price_usd: typeof payload.price === 'number' ? payload.price : item.price_usd, usd_status: status, source_usd: source, candidate_price_usd: candidatePrice }),
        observed_at: typeof payload.observed_at === 'string' ? payload.observed_at : item.observed_at,
        canonical_at: typeof payload.canonical_at === 'string' ? payload.canonical_at : item.canonical_at,
        age_seconds: typeof payload.age_seconds === 'number' ? payload.age_seconds : item.age_seconds,
        candidate_provider: candidate && typeof candidate.provider_name === 'string' ? candidate.provider_name : candidate && typeof candidate.provider_id === 'string' ? candidate.provider_id : item.candidate_provider,
        candidate_observed_at: candidate && typeof candidate.observed_at === 'string' ? candidate.observed_at : typeof payload.candidate_observed_at === 'string' ? payload.candidate_observed_at : item.candidate_observed_at,
        difference_percent: candidate && typeof candidate.difference_percent === 'number' ? candidate.difference_percent : item.difference_percent,
        verification_status: typeof payload.verification_status === 'string' ? payload.verification_status : item.verification_status,
      })));
      setLastRefreshAt(typeof payload.canonical_at === 'string' ? payload.canonical_at : new Date().toISOString());
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
        lastEventsRef.current.clear();
        setSocketStatus('live');
      };
      socket.onmessage = (event) => {
        lastMessageAt = Date.now();
        try { mergeEvent(JSON.parse(event.data)); } catch { /* Ignore malformed events while the socket remains healthy. */ }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (stopped) return;
        setSocketStatus('fallback');
        retryCount += 1;
        const baseDelay = Math.min(1_000 * 2 ** Math.max(retryCount - 1, 0), 30_000);
        retryTimer = setTimeout(connect, Math.round(baseDelay * (0.8 + Math.random() * 0.4)));
      };
    };
    const reconnect = () => {
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
    window.addEventListener('online', reconnect);
    window.addEventListener('offline', switchToPolling);
    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      clearInterval(watchdog);
      socket?.close();
      window.removeEventListener('online', reconnect);
      window.removeEventListener('offline', switchToPolling);
    };
  }, []);

  const orderedAssets = useMemo(() => {
    return assetOrder.map((id) => {
      const live = pricesData.find((a) => a.asset === id);
      return buildLiveCard(live, id, ASSET_ICONS[id]);
    });
  }, [assetOrder, pricesData]);

  useEffect(() => {
    setExpandedSources({});
    setSourceDetails({});
    setSourceErrors({});
  }, [currencyMode]);

  const toggleSourcePanel = async (assetId: AssetId) => {
    const open = !expandedSources[assetId];
    setExpandedSources((current) => ({ ...current, [assetId]: open }));
    if (!open || sourceDetails[assetId] || sourceLoading[assetId]) return;
    setSourceLoading((current) => ({ ...current, [assetId]: true }));
    setSourceErrors((current) => ({ ...current, [assetId]: '' }));
    try {
      const details = await api.instruments.sources(INSTRUMENT_IDS[assetId][currencyMode]);
      setSourceDetails((current) => ({ ...current, [assetId]: details }));
    } catch (error) {
      setSourceErrors((current) => ({ ...current, [assetId]: error instanceof Error ? error.message : 'Source data is unavailable' }));
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

  const updateScrubPoint = (asset: AssetCard, clientX: number, clientY: number) => {
    const chartNode = document.getElementById(`asset-chart-${asset.id}`);
    if (!chartNode) return;
    const rect = chartNode.getBoundingClientRect();

    const paddingX = 64;
    let relativeX = clientX - rect.left - paddingX;
    const chartWidth = rect.width - paddingX * 2;
    relativeX = Math.max(0, Math.min(relativeX, chartWidth));

    const totalPoints = asset.history.length;
    if (totalPoints === 0) return;

    const rawIndex = Math.round((relativeX / chartWidth) * (totalPoints - 1));
    const safeIndex = Math.max(0, Math.min(rawIndex, totalPoints - 1));

    setActivePointIndexByAsset((prev) => ({ ...prev, [asset.id]: safeIndex }));
    setTooltipPositionByAsset((prev) => ({
      ...prev,
      [asset.id]: {
        x: Math.max(10, Math.min(clientX - rect.left, rect.width - 120)),
        y: Math.max(10, clientY - rect.top - 80)
      }
    }));
  };

  const currentUsdt = orderedAssets.find((a) => a.id === 'usdt');
  const usdToTomanRate = currentUsdt?.priceToman && currentUsdt.priceUsd ? currentUsdt.priceToman / currentUsdt.priceUsd : null;

  const t = {
    currencyView: { fa: 'نمایش بر اساس:', en: 'Currency:' },
    usd: { fa: 'دلار', en: 'USD' },
    toman: { fa: 'تومان', en: 'Toman' },
    source: { fa: 'منبع', en: 'Source' },
    updatedAt: { fa: 'آخرین بروزرسانی', en: 'Updated' },
    loading: { fa: 'در حال بروزرسانی...', en: 'Syncing...' },
    createAlert: { fa: 'ایجاد هشدار', en: 'Create Alert' },
    alertFor: { fa: 'هشدار برای', en: 'Alert for' },
    targetPrice: { fa: 'قیمت هدف', en: 'Target Price' },
    notifyVia: { fa: 'اطلاع‌رسانی از طریق', en: 'Notify via' },
    appAlert: { fa: 'اعلان برنامه', en: 'App Notification' },
    emailAlert: { fa: 'ایمیل', en: 'Email' },
    smsAlert: { fa: 'پیامک', en: 'SMS' },
    cancel: { fa: 'انصراف', en: 'Cancel' },
    save: { fa: 'ذخیره', en: 'Save Alert' },
    alertSuccess: { fa: 'هشدار با موفقیت ثبت شد', en: 'Alert created successfully' },
    dragToInspect: { fa: 'برای مشاهده قیمت در زمان‌های مختلف روی نمودار بکشید', en: 'Drag on chart to inspect history' },
    live: { fa: 'زنده', en: 'Live' },
    cached: { fa: 'حافظه موقت', en: 'Cached' },
    unavailable: { fa: 'خارج از دسترس', en: 'Down' },
    cacheAge: { fa: 'عمر داده', en: 'Age' },
    minute: { fa: 'دقیقه', en: 'min' },
    dragToReorder: { fa: 'برای جابجایی بکشید', en: 'Drag to reorder' },
    degradedNotice: { fa: '⚠️ برخی از منابع تامین قیمت در دسترس نیستند. آخرین قیمت‌های ذخیره شده نمایش داده می‌شوند.', en: '⚠️ Some pricing providers are down. Displaying latest known cached prices.' }
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
  const hasDegradedSources = orderedAssets.some((asset) => !healthyStatuses.has(asset.usdStatus) || !healthyStatuses.has(asset.tomanStatus));

  return (
    <div className="space-y-6">

      <div className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border p-3 ${isDark ? 'border-white/5 bg-[#0E0E0E]/60' : 'border-black/5 bg-white/60'}`}>
        <div className="flex rounded-xl bg-black/5 p-1 dark:bg-black/40" dir="ltr">
          {TIMEFRAMES.map((value) => <button key={value} type="button" onClick={() => setTimeframe(value)} className={`rounded-lg px-3 py-1.5 text-xs font-bold ${timeframe === value ? 'bg-[#D4AF37] text-black' : 'text-slate-500 dark:text-[#A89668]'}`}>{value}</button>)}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-semibold ${socketStatus === 'live' ? 'bg-emerald-500/10 text-emerald-500' : socketStatus === 'connecting' ? 'bg-amber-500/10 text-amber-500' : 'bg-slate-500/10 text-slate-500'}`}>
            {socketStatus === 'live' ? <Radio size={12} /> : <WifiOff size={12} />}
            {socketStatus === 'live' ? (language === 'fa' ? 'پخش زنده' : 'Live stream') : socketStatus === 'connecting' ? (language === 'fa' ? 'در حال اتصال' : 'Connecting') : (language === 'fa' ? 'دریافت دوره‌ای' : 'Polling fallback')}
          </span>
          {lastRefreshAt && <span className="text-slate-500" dir="ltr">{new Date(lastRefreshAt).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</span>}
        </div>
      </div>

      {loadError && <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 text-xs text-red-500">{loadError}</div>}
      {hasDegradedSources && <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-500">{t.degradedNotice[language]}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {orderedAssets.map((asset, idx) => {
        const fallbackValue = currencyMode === 'usd' 
          ? (asset.priceUsd ?? (asset.priceToman && usdToTomanRate ? asset.priceToman / usdToTomanRate : null))
          : (asset.priceToman ?? (asset.priceUsd && usdToTomanRate ? asset.priceUsd * usdToTomanRate : null));
        const activeStatus = currencyMode === 'usd' ? asset.usdStatus : asset.tomanStatus;
        const activeSource = currencyMode === 'usd' ? asset.sourceUsd : asset.sourceToman;
        const candidatePrice = currencyMode === 'usd' ? asset.candidatePriceUsd : asset.candidatePriceToman;
        const isAnomaly = activeStatus === 'verifying' || activeStatus === 'suspicious' || activeStatus === 'suspicious_unconfirmed';
        const sourceRows = [...(sourceDetails[asset.id]?.sources ?? [])].sort((left, right) => {
          const rank: Record<string, number> = { primary: 0, verifier: 1, fallback: 2, derived: 3 };
          const leftOld = left.status === 'stale' || left.status === 'expired' || left.status === 'rejected' ? 10 : 0;
          const rightOld = right.status === 'stale' || right.status === 'expired' || right.status === 'rejected' ? 10 : 0;
          return leftOld + (rank[left.role ?? ''] ?? 4) - rightOld - (rank[right.role ?? ''] ?? 4);
        });

        const resolvedHistory = asset.history.length ? asset.history : [
          { timestamp: new Date().toISOString(), value_usd: asset.priceUsd, value_toman: asset.priceToman }
        ];

        const activeIndex = Math.min(
          activePointIndexByAsset[asset.id] ?? Math.max(resolvedHistory.length - 1, 0),
          Math.max(resolvedHistory.length - 1, 0)
        );

        const selectedPoint = resolvedHistory[activeIndex] ?? {
          timestamp: new Date().toISOString(),
          value_usd: asset.priceUsd,
          value_toman: asset.priceToman
        };

        const chartData = resolvedHistory.map((point) => ({
          time: new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          value: toChartValue(point, currencyMode, fallbackValue)
        }));

        const selectedChartPoint = chartData[activeIndex] ?? chartData[chartData.length - 1] ?? { time: '', value: fallbackValue };
        const chartColor = isDark ? CHART_COLORS[asset.id].dark : CHART_COLORS[asset.id].light;
        const tooltipPosition = tooltipPositionByAsset[asset.id];

        return (
          <motion.div
            key={asset.id}
            layoutId={asset.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0, scale: dragOverAssetId === asset.id ? 1.02 : 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{
              delay: idx * 0.05,
              duration: 0.35,
              ease: [0.22, 1, 0.36, 1],
              layout: { type: 'spring', damping: 28, stiffness: 330 }
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
              }
            }}
            onDragEnd={() => {
              setDraggedAssetId(null);
              setDragOverAssetId(null);
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
                  : ''
              } hover:shadow-[0_8px_32px_rgba(212,175,55,0.15)] hover:-translate-y-1`}
            >
              <CardHeader className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-2">
                  <button
                    type="button"
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.effectAllowed = 'move';
                      setDraggedAssetId(asset.id);
                    }}
                    onDragEnd={() => {
                      setDraggedAssetId(null);
                      setDragOverAssetId(null);
                    }}
                    className={`mt-1 inline-flex h-10 w-10 shrink-0 cursor-grab items-center justify-center rounded-xl border transition active:cursor-grabbing ${
                      isDark
                        ? 'border-white/10 text-[#D4AF37] hover:bg-white/5'
                        : 'border-black/10 text-[#9D7A20] hover:bg-black/5'
                    }`}
                    aria-label="Reorder"
                    title="Reorder"
                  >
                    <GripVertical size={18} />
                  </button>
                  
                  <div>
                    <CardTitle className={`flex items-center gap-2 text-lg font-semibold ${isDark ? 'text-[#E8D9AE]' : 'text-[#6A4D16]'}`}>
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl text-[#111111]" style={{ backgroundColor: chartColor }}>
                        <asset.icon size={20} />
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
                      {asset.ageSeconds !== null ? (
                        <span className={`${isDark ? 'text-[#BCA96F]' : 'text-[#7D6023]'}`}>
                          {t.cacheAge[language]}: {formatAge(asset.ageSeconds, language)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className={`flex items-center gap-1 rounded-2xl px-3 py-1.5 text-xs font-semibold backdrop-blur-md ${
                    asset.isUp
                      ? isDark ? 'bg-emerald-500/20 text-emerald-400' : 'bg-emerald-100 text-emerald-700'
                      : isDark ? 'bg-red-500/20 text-red-400' : 'bg-red-100 text-red-700'
                  }`}>
                    {Number.isFinite(asset.changePercent) && (asset.isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />)}
                    <span dir="ltr">{Number.isFinite(asset.changePercent) ? `${Math.abs(asset.changePercent).toFixed(2)}%` : 'N/A'}</span>
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
                    {formatPrice(toChartValue(selectedPoint, currencyMode, fallbackValue), currencyMode, language)}
                  </div>
                  <span className={`text-sm font-medium ${isDark ? 'text-[#CDBB8C]' : 'text-[#8A6B26]'}`}>
                    {activeCurrencyLabel}
                  </span>
                </div>

                <div className={`mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2 text-xs ${isDark ? 'border-white/5 bg-black/20 text-[#A89668]' : 'border-black/5 bg-white/60 text-[#7A5E24]'}`}>
                  <div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-1 font-semibold ${isDark ? STATUS_COLORS[activeStatus].dark : STATUS_COLORS[activeStatus].light}`}>{statusLabel(activeStatus)}</span><span className="inline-flex items-center gap-1"><Clock3 size={12} />{formatAge(asset.ageSeconds, language)}</span>{(asset.canonicalAt || asset.observedAt) && <span dir="ltr">{new Date(asset.canonicalAt ?? asset.observedAt ?? '').toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</span>}<span className="max-w-40 truncate" title={activeSource}>{activeSource}</span></div>
                  <button type="button" onClick={() => void toggleSourcePanel(asset.id)} className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 font-bold ${isAnomaly ? 'border-orange-400/50 bg-orange-500/10 text-orange-400' : 'border-[#D4AF37]/20 text-[#D4AF37]'}`}>
                    {language === 'fa' ? 'مقایسه منابع' : 'Compare sources'}<ChevronDown size={13} className={expandedSources[asset.id] ? 'rotate-180' : ''} />
                  </button>
                </div>

                {isAnomaly && candidatePrice !== null && <div className={`mb-4 rounded-xl border p-3 text-xs ${isDark ? 'border-orange-500/30 bg-orange-500/5 text-orange-200' : 'border-orange-300 bg-orange-50 text-orange-800'}`}><div className="mb-1 flex items-center gap-2 font-bold"><AlertTriangle size={14} />{language === 'fa' ? 'قیمت مشکوک؛ قیمت پذیرفته‌شده نمایش داده می‌شود.' : 'Suspicious candidate; showing the last accepted price.'}</div><div className="flex flex-wrap gap-3" dir="ltr"><span>{formatPrice(candidatePrice, currencyMode, language)} {activeCurrencyLabel}</span>{asset.candidateProvider && <span>{asset.candidateProvider}</span>}{asset.candidateObservedAt && <span>{new Date(asset.candidateObservedAt).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</span>}{asset.differencePercent !== null && <span>{asset.differencePercent.toFixed(2)}%</span>}{asset.verificationStatus && <span>{asset.verificationStatus}</span>}</div></div>}

                {expandedSources[asset.id] && <div className={`mb-4 overflow-hidden rounded-xl border ${isDark ? 'border-white/5 bg-black/20' : 'border-black/5 bg-white/60'}`}>
                  {sourceLoading[asset.id] ? <div className="p-4 text-center text-xs">{language === 'fa' ? 'در حال دریافت داده ذخیره‌شده...' : 'Loading stored source data...'}</div> : sourceErrors[asset.id] ? <div className="p-4 text-center text-xs text-red-500">{sourceErrors[asset.id]}</div> : sourceRows.length === 0 ? <div className="p-4 text-center text-xs text-slate-500">{language === 'fa' ? 'داده منبعی ذخیره نشده است.' : 'No stored source quotes.'}</div> : <div className="divide-y divide-white/5">{sourceRows.map((source, index) => { const old = source.status === 'stale' || source.status === 'expired' || source.status === 'rejected'; return <div key={String(source.id ?? `${source.provider_id ?? 'source'}-${index}`)} className={`grid grid-cols-[1fr_auto] gap-3 px-3 py-2.5 text-xs ${old ? 'opacity-55 grayscale' : ''}`}><div><div className="font-bold">{source.provider_name ?? source.provider_id ?? 'Source'}</div><div className="mt-1 flex flex-wrap gap-2 text-slate-500"><span>{source.role ?? 'source'}</span><span>{source.status ?? 'unknown'}</span><span>{formatAge(source.age_seconds ?? null, language)}</span>{source.observed_at && <span dir="ltr">{new Date(source.observed_at).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</span>}{source.rejection_reason && <span>{source.rejection_reason}</span>}</div></div><div className="text-end font-bold" dir="ltr"><div>{formatPrice(source.price, currencyMode, language)}</div>{source.difference_percent !== null && source.difference_percent !== undefined && <div className="text-[10px] text-[#D4AF37]">{source.difference_percent.toFixed(2)}%</div>}</div></div>; })}</div>}
                </div>}
                
                {asset.chartError && asset.history.length === 0 && asset.priceUsd === null && asset.priceToman === null ? (
                  <div className={`flex h-[260px] w-full flex-col items-center justify-center rounded-[1.5rem] border backdrop-blur-md ${
                    isDark ? 'border-red-500/20 bg-[#1A0B0B]/50' : 'border-red-200 bg-[#FFF0F0]/50'
                  }`}>
                    <div className={`text-sm font-semibold ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                      {asset.chartErrorMessage[language]}
                    </div>
                  </div>
                ) : (
                  <>
                    <div className={`mb-2 text-[10px] ${isDark ? 'text-[#887850]' : 'text-[#A8883A]'}`}
                      dir="ltr" title={`USD source: ${asset.sourceUsd}\nToman source: ${asset.sourceToman}`}
                    >
                      USD: {asset.sourceUsd} | Toman: {asset.sourceToman}
                    </div>
                    <div className={`mb-2 text-xs ${isDark ? 'text-[#A89668]' : 'text-[#8A6A25]'}`}>{t.dragToInspect[language]}</div>
                    <div
                      id={`asset-chart-${asset.id}`}
                      className={`relative h-[260px] w-full rounded-[1.5rem] border p-2 backdrop-blur-md transition-colors ${
                        isDark 
                          ? 'border-white/5 bg-[#111111]/40' 
                          : 'border-black/5 bg-white/40'
                      }`}
                      dir="ltr"
                      onMouseDown={(event) => {
                        setIsScrubbingByAsset((prev) => ({ ...prev, [asset.id]: true }));
                        updateScrubPoint(asset, event.clientX, event.clientY);
                      }}
                      onMouseMove={(event) => {
                        if (isScrubbingByAsset[asset.id]) {
                          updateScrubPoint(asset, event.clientX, event.clientY);
                        }
                      }}
                      onMouseLeave={() => {
                        setIsScrubbingByAsset((prev) => ({ ...prev, [asset.id]: false }));
                      }}
                      onMouseUp={() => {
                        setIsScrubbingByAsset((prev) => ({ ...prev, [asset.id]: false }));
                      }}
                    >
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData}>
                          <CartesianGrid stroke={isDark ? '#D4AF37' : '#B68A2A'} strokeOpacity={isDark ? 0.12 : 0.18} vertical={false} />
                          <XAxis dataKey="time" tick={{ fill: isDark ? '#AA986A' : '#7A5E24', fontSize: 11 }} axisLine={false} tickLine={false} />
                          <YAxis domain={['dataMin', 'dataMax']} tick={{ fill: isDark ? '#AA986A' : '#7A5E24', fontSize: 11 }} axisLine={false} tickLine={false} width={56} />
                          <ReferenceLine x={selectedChartPoint.time} stroke={chartColor} strokeOpacity={0.65} strokeDasharray="5 4" />
                          <Line
                            type="monotone"
                            dataKey="value"
                            stroke={chartColor}
                            strokeWidth={3}
                            dot={false}
                            activeDot={{ r: 6, fill: chartColor, stroke: isDark ? '#0A0A0A' : '#FFFFFF', strokeWidth: 2 }}
                            isAnimationActive={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>

                      {isScrubbingByAsset[asset.id] && tooltipPosition && (
                        <div
                          className={`pointer-events-none absolute z-10 flex flex-col items-center gap-1 rounded-xl p-2 shadow-lg backdrop-blur-md ${
                            isDark ? 'bg-[#0E0E0E]/90 border border-white/10' : 'bg-white/90 border border-black/10'
                          }`}
                          style={{
                            left: tooltipPosition.x,
                            top: tooltipPosition.y,
                            transform: 'translate(-50%, -100%)'
                          }}
                        >
                          <span className={`text-xs font-semibold ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                            {formatPrice(selectedChartPoint.value, currencyMode, language)}
                          </span>
                          <span className={`text-[10px] ${isDark ? 'text-[#A89668]' : 'text-[#8A6A25]'}`}>
                            {selectedChartPoint.time}
                          </span>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </motion.div>
        );
      })}</div>

      <Modal isOpen={isAlertModalOpen} onClose={() => setIsAlertModalOpen(false)} title={t.createAlert[language]}>
        <div className="space-y-6 pt-4">
          <div className="space-y-2">
            <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
              {t.alertFor[language]}
            </label>
            <div className={`flex items-center gap-3 rounded-[1.5rem] border p-3 ${isDark ? 'border-[#D4AF37]/20 bg-[#111111]' : 'border-[#D4AF37]/35 bg-[#FFF0CC]'}`}>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#D4AF37] text-[#0A0A0A]">
                {React.createElement(ASSET_ICONS[selectedAssetForAlert], { size: 20 })}
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
              value={alertTarget}
              onChange={(event) => setAlertTarget(event.target.value)}
              className={`h-12 rounded-2xl text-lg font-bold tracking-wider ${
                isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3]' : 'border-[#D4AF37]/30 bg-white text-[#3B2E13]'
              }`}
            />
          </div>

          <div className="space-y-4 pt-2">
            <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
              {t.notifyVia[language]}
            </label>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className={`text-sm ${isDark ? 'text-[#CDBB8C]' : 'text-[#8A6B26]'}`}>{t.appAlert[language]}</span>
                <Switch checked={alertNotifyApp} onCheckedChange={setAlertNotifyApp} />
              </div>
              <div className="flex items-center justify-between">
                <span className={`text-sm ${isDark ? 'text-[#CDBB8C]' : 'text-[#8A6B26]'}`}>{t.emailAlert[language]}</span>
                <Switch checked={alertNotifyEmail} onCheckedChange={setAlertNotifyEmail} />
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
              className={`h-12 flex-1 rounded-2xl border-0 text-black shadow-lg hover:shadow-xl transition-all ${
                isDark ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB]' : 'bg-[#D4AF37] hover:bg-[#E8C45A]'
              }`}
              disabled={isSavingAlert || !alertTarget}
              onClick={async () => {
                const value = Number(alertTarget);
                if (!Number.isFinite(value) || value <= 0) return;
                setIsSavingAlert(true);
                try {
                  await api.alerts.create({ asset: selectedAssetForAlert, target_price: value, alert_type: 'price', formula: null, currency_mode: currencyMode, condition: 'above', notify_app: alertNotifyApp, notify_email: alertNotifyEmail, notify_webhook: false, webhook_url: null, enable_dlq: false });
                  toast.success(t.alertSuccess[language]);
                  setAlertTarget('');
                  setIsAlertModalOpen(false);
                } catch (error) {
                  toast.error(error instanceof Error ? error.message : (language === 'fa' ? 'ثبت هشدار ناموفق بود' : 'Failed to save alert'));
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
    </div>
  );
}
