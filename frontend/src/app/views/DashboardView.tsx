import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import {
  LineChart,
  Line,
  ResponsiveContainer,
  YAxis,
  XAxis,
  CartesianGrid,
  ReferenceLine
} from 'recharts';
import {
  BellPlus,
  ArrowUpRight,
  ArrowDownRight,
  Gem,
  Coins,
  GripVertical,
  Bitcoin,
  CircleDollarSign
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { useAppContext } from '../context/AppContext';
import { Modal } from '../components/ui/Modal';
import { Input } from '../components/ui/input';
import { Switch } from '../components/ui/switch';
import { toast } from 'sonner';
import { formatPrice, getPrices, type CurrencyMode, type PriceAsset } from '../services/api';

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
  usdStatus: 'live' | 'cached' | 'unavailable';
  tomanStatus: 'live' | 'cached' | 'unavailable';
  staleMinutes: number | null;
  chartError: boolean;
  chartErrorMessage: { fa: string; en: string };
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
  btc: { dark: '#9C7A18', light: '#7B5A00' }
};

const STATUS_COLORS: Record<AssetCard['usdStatus'], { dark: string; light: string }> = {
  live: { dark: 'bg-emerald-500/15 text-emerald-300', light: 'bg-emerald-100 text-emerald-700' },
  cached: { dark: 'bg-amber-500/20 text-amber-200', light: 'bg-amber-100 text-amber-700' },
  unavailable: { dark: 'bg-red-500/20 text-red-200', light: 'bg-red-100 text-red-700' }
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
  change_percent: 0,
  trend: 'up',
  source_usd: 'unavailable',
  source_toman: 'unavailable',
  usd_status: 'unavailable',
  toman_status: 'unavailable',
  stale_minutes: null,
  chart_error: true,
  chart_error_message: {
    fa: 'امکان دریافت اطلاعات وجود ندارد',
    en: 'Unable to fetch data'
  },
  history: []
});

const EMPTY_ASSETS: PriceAsset[] = DEFAULT_ASSET_ORDER.map(buildPlaceholderAsset);

const buildLiveCard = (asset: PriceAsset | undefined, id: AssetId, icon: LucideIcon): AssetCard => {
  if (!asset) {
    const placeholder = buildPlaceholderAsset(id);
    return {
      id,
      label: {
        fa: placeholder.label_fa,
        en: placeholder.label_en
      },
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
      chartErrorMessage: placeholder.chart_error_message
    };
  }

  return {
    id,
    label: {
      fa: asset.label_fa,
      en: asset.label_en
    },
    icon,
    priceUsd: asset.price_usd,
    priceToman: asset.price_toman,
    changePercent: asset.change_percent,
    isUp: asset.trend === 'up',
    history: asset.history,
    sourceUsd: asset.source_usd,
    sourceToman: asset.source_toman,
    usdStatus: asset.usd_status,
    tomanStatus: asset.toman_status,
    staleMinutes: asset.stale_minutes,
    chartError: asset.chart_error,
    chartErrorMessage: asset.chart_error_message
  };
};

const toChartValue = (point: AssetPoint, currencyMode: CurrencyMode, fallback: number): number => {
  const selected = currencyMode === 'usd' ? point.value_usd : point.value_toman;
  const alternate = currencyMode === 'usd' ? point.value_toman : point.value_usd;
  if (typeof selected === 'number') {
    return selected;
  }
  if (typeof alternate === 'number') {
    return alternate;
  }
  return fallback;
};

export function DashboardView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';

  const [selectedAsset, setSelectedAsset] = useState<AssetId | null>(null);
  const [assetOrder, setAssetOrder] = useState<AssetId[]>(getInitialAssetOrder);
  const [draggedAssetId, setDraggedAssetId] = useState<AssetId | null>(null);
  const [dragOverAssetId, setDragOverAssetId] = useState<AssetId | null>(null);
  const [activePointIndexByAsset, setActivePointIndexByAsset] = useState<Record<string, number>>({});
  const [isScrubbingByAsset, setIsScrubbingByAsset] = useState<Record<string, boolean>>({});
  const [tooltipPositionByAsset, setTooltipPositionByAsset] = useState<
    Partial<Record<AssetId, TooltipPosition>>
  >({});

  const [currencyMode, setCurrencyMode] = useState<CurrencyMode>('usd');
  const [assets, setAssets] = useState<PriceAsset[]>(EMPTY_ASSETS);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sourceLabel, setSourceLabel] = useState<{ usd: string; toman: string }>({
    usd: '-',
    toman: '-'
  });
  const [lastRefreshAt, setLastRefreshAt] = useState<string>('');

  const closeAlertModal = () => setSelectedAsset(null);

  useEffect(() => {
    try {
      window.localStorage.setItem(CHART_ORDER_STORAGE_KEY, JSON.stringify(assetOrder));
    } catch {
      // Ignore storage errors (private mode, full storage, etc.)
    }
  }, [assetOrder]);

  useEffect(() => {
    let isMounted = true;

    const loadPrices = async () => {
      try {
        setIsLoading(true);
        const response = await getPrices();
        if (!isMounted) {
          return;
        }

        setAssets(response.assets.length > 0 ? response.assets : EMPTY_ASSETS);
        setSourceLabel(response.source);
        setLastRefreshAt(response.refreshed_at);
        setLoadError(null);
      } catch (error) {
        if (!isMounted) {
          return;
        }

        const message = error instanceof Error ? error.message : 'Failed to fetch prices';
        setLoadError(message);
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    void loadPrices();
    const intervalId = window.setInterval(() => {
      void loadPrices();
    }, 30000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const usdToTomanRate = useMemo(() => {
    const usdt = assets.find((asset) => asset.asset === 'usdt');
    if (usdt && typeof usdt.price_toman === 'number' && typeof usdt.price_usd === 'number' && usdt.price_usd > 0) {
      return usdt.price_toman / usdt.price_usd;
    }

    const gold = assets.find((asset) => asset.asset === 'gold');
    if (gold && typeof gold.price_toman === 'number' && typeof gold.price_usd === 'number' && gold.price_usd > 0) {
      return gold.price_toman / gold.price_usd;
    }

    return 60000;
  }, [assets]);

  const t = {
    quickAlert: { fa: 'هشدار سریع', en: 'Quick Alert' },
    dragToReorder: { fa: 'برای جابجایی بکشید', en: 'Drag to reorder' },
    dragToInspect: {
      fa: 'برای دیدن قیمت در زمان های مختلف روی نمودار بکشید',
      en: 'Drag on the chart to inspect prices over time'
    },
    createAlertTitle: { fa: 'ایجاد هشدار جدید', en: 'Create New Alert' },
    priceTarget: { fa: 'قیمت هدف', en: 'Target Price' },
    notifyVia: { fa: 'اطلاع رسانی از طریق', en: 'Notify via' },
    above: { fa: 'بالاتر از', en: 'Above' },
    below: { fa: 'پایین تر از', en: 'Below' },
    saveAlert: { fa: 'ثبت هشدار', en: 'Save Alert' },
    time: { fa: 'زمان', en: 'Time' },
    value: { fa: 'قیمت', en: 'Price' },
    usd: { fa: 'دلار', en: 'USD' },
    toman: { fa: 'تومان', en: 'Toman' },
    currencyView: { fa: 'نمایش قیمت', en: 'Currency View' },
    source: { fa: 'منبع', en: 'Source' },
    updatedAt: { fa: 'آخرین بروزرسانی', en: 'Last update' },
    loading: { fa: 'در حال دریافت قیمت ها...', en: 'Loading live prices...' },
    retry: { fa: 'تلاش مجدد', en: 'Retry' },
    cacheAge: { fa: 'آخرین بروزرسانی', en: 'Last updated' },
    minute: { fa: 'دقیقه پیش', en: 'minutes ago' },
    status: { fa: 'وضعیت', en: 'Status' },
    live: { fa: 'زنده', en: 'Live' },
    cached: { fa: 'کش', en: 'Cached' },
    unavailable: { fa: 'ناموجود', en: 'Unavailable' },
    chartUnavailable: { fa: 'نمودار در دسترس نیست', en: 'Chart data unavailable' }
  };

  const cardMap: Record<AssetId, AssetCard> = useMemo(() => {
    const iconMap: Record<AssetId, LucideIcon> = {
      gold: Gem,
      silver: Coins,
      usdt: CircleDollarSign,
      btc: Bitcoin
    };

    return DEFAULT_ASSET_ORDER.reduce<Record<AssetId, AssetCard>>((acc, id) => {
      const asset = assets.find((item) => item.asset === id);
      acc[id] = buildLiveCard(asset, id, iconMap[id]);
      return acc;
    }, {} as Record<AssetId, AssetCard>);
  }, [assets]);

  const orderedAssets = useMemo(() => assetOrder.map((id) => cardMap[id]), [assetOrder, cardMap]);

  const reorderAssets = (fromId: AssetId, toId: AssetId) => {
    if (fromId === toId) {
      return;
    }

    setAssetOrder((prev) => {
      const fromIndex = prev.indexOf(fromId);
      const toIndex = prev.indexOf(toId);

      if (fromIndex < 0 || toIndex < 0) {
        return prev;
      }

      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  };

  const updateScrubPoint = (asset: AssetCard, clientX: number, clientY: number) => {
    const chartElement = document.getElementById(`asset-chart-${asset.id}`);
    if (!chartElement || asset.history.length === 0) {
      return;
    }

    const rect = chartElement.getBoundingClientRect();
    const ratio = (clientX - rect.left) / rect.width;
    const clampedRatio = Math.max(0, Math.min(1, ratio));
    const index = Math.round(clampedRatio * (asset.history.length - 1));

    const tooltipX = Math.min(rect.width - 12, Math.max(8, clientX - rect.left + 14));
    const tooltipY = Math.min(rect.height - 12, Math.max(10, clientY - rect.top + 10));

    setActivePointIndexByAsset((prev) => ({ ...prev, [asset.id]: index }));
    setTooltipPositionByAsset((prev) => ({
      ...prev,
      [asset.id]: { x: tooltipX, y: tooltipY }
    }));
  };

  const activeCurrencyLabel = currencyMode === 'usd' ? t.usd[language] : t.toman[language];

  const statusLabel = (status: 'live' | 'cached' | 'unavailable') => {
    if (status === 'live') {
      return t.live[language];
    }
    if (status === 'cached') {
      return t.cached[language];
    }
    return t.unavailable[language];
  };

  return (
    <div className="space-y-6">
      <div
        className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border p-3 ${
          isDark ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/80' : 'border-[#D4AF37]/35 bg-[#FFF5DF]/95'
        }`}
      >
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold ${isDark ? 'text-[#CDBB8C]' : 'text-[#6E531A]'}`}>
            {t.currencyView[language]}
          </span>
          <div
            className={`rounded-xl border p-1 ${
              isDark ? 'border-[#D4AF37]/20 bg-[#111111]' : 'border-[#D4AF37]/35 bg-[#FFF0CC]'
            }`}
          >
            <button
              type="button"
              onClick={() => setCurrencyMode('usd')}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                currencyMode === 'usd'
                  ? 'bg-[#D4AF37] text-[#0A0A0A]'
                  : isDark
                    ? 'text-[#CDBB8C]'
                    : 'text-[#6E531A]'
              }`}
            >
              {t.usd[language]}
            </button>
            <button
              type="button"
              onClick={() => setCurrencyMode('toman')}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                currencyMode === 'toman'
                  ? 'bg-[#D4AF37] text-[#0A0A0A]'
                  : isDark
                    ? 'text-[#CDBB8C]'
                    : 'text-[#6E531A]'
              }`}
            >
              {t.toman[language]}
            </button>
          </div>
        </div>

        <div className={`text-xs ${isDark ? 'text-[#A89668]' : 'text-[#765D27]'}`} dir="ltr">
          {t.source[language]}: USD={sourceLabel.usd} | Toman={sourceLabel.toman}
          {lastRefreshAt ? ` | ${t.updatedAt[language]}: ${new Date(lastRefreshAt).toLocaleTimeString()}` : ''}
          {isLoading ? ` | ${t.loading[language]}` : ''}
          {loadError ? ` | ${loadError}` : ''}
        </div>
      </div>

      {orderedAssets.map((asset, idx) => {
        const fallbackValue =
          currencyMode === 'usd'
            ? (asset.priceUsd ?? (asset.priceToman ? asset.priceToman / usdToTomanRate : 0))
            : (asset.priceToman ?? (asset.priceUsd ? asset.priceUsd * usdToTomanRate : 0));

        const resolvedHistory = asset.history.length
          ? asset.history
          : [
              {
                timestamp: new Date().toISOString(),
                value_usd: asset.priceUsd,
                value_toman: asset.priceToman
              }
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
          time: new Date(point.timestamp).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit'
          }),
          value: toChartValue(point, currencyMode, fallbackValue)
        }));

        const selectedChartPoint = chartData[activeIndex] ?? chartData[chartData.length - 1];
        const chartColor = isDark ? CHART_COLORS[asset.id].dark : CHART_COLORS[asset.id].light;
        const tooltipPosition = tooltipPositionByAsset[asset.id];

        return (
          <motion.div
            key={asset.id}
            layout
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
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
              className={`relative overflow-hidden transition-all duration-200 ${
                isDark
                  ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/95 shadow-[0_12px_36px_rgba(0,0,0,0.35)]'
                  : 'border-[#D4AF37]/35 bg-[#FFF6E2] shadow-[0_8px_24px_rgba(102,78,30,0.16)]'
              } ${
                dragOverAssetId === asset.id
                  ? 'ring-1 ring-[#D4AF37]/45 shadow-[0_0_0_1px_rgba(212,175,55,0.18),0_12px_36px_rgba(0,0,0,0.2)]'
                  : ''
              }`}
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
                    className={`mt-1 inline-flex h-8 w-8 shrink-0 cursor-grab items-center justify-center rounded-md border transition active:cursor-grabbing ${
                      isDark
                        ? 'border-[#D4AF37]/30 text-[#D4AF37] hover:bg-[#D4AF37]/10'
                        : 'border-[#C79A2B]/40 text-[#9D7A20] hover:bg-[#D4AF37]/15'
                    }`}
                    aria-label={t.dragToReorder[language]}
                    title={t.dragToReorder[language]}
                  >
                    <GripVertical size={16} />
                  </button>
                  <div>
                    <CardTitle className={`flex items-center gap-2 text-base font-semibold ${isDark ? 'text-[#E8D9AE]' : 'text-[#6A4D16]'}`}>
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg text-[#111111]" style={{ backgroundColor: chartColor }}>
                        <asset.icon size={18} />
                      </div>
                      {asset.label[language]}
                    </CardTitle>
                    <p className={`mt-1 text-xs ${isDark ? 'text-[#A89668]' : 'text-[#8A6B26]'}`}>
                      {t.dragToReorder[language]}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                      <span
                        className={`rounded-full px-2 py-0.5 font-semibold ${
                          isDark ? STATUS_COLORS[asset.usdStatus].dark : STATUS_COLORS[asset.usdStatus].light
                        }`}
                      >
                        USD {statusLabel(asset.usdStatus)}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 font-semibold ${
                          isDark ? STATUS_COLORS[asset.tomanStatus].dark : STATUS_COLORS[asset.tomanStatus].light
                        }`}
                      >
                        Toman {statusLabel(asset.tomanStatus)}
                      </span>
                      {asset.staleMinutes !== null ? (
                        <span className={`${isDark ? 'text-[#BCA96F]' : 'text-[#7D6023]'}`}>
                          {t.cacheAge[language]}: {asset.staleMinutes} {t.minute[language]}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div
                    className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
                      asset.isUp
                        ? isDark
                          ? 'bg-emerald-500/15 text-emerald-300'
                          : 'bg-emerald-100 text-emerald-700'
                        : isDark
                          ? 'bg-red-500/15 text-red-300'
                          : 'bg-red-100 text-red-700'
                    }`}
                    dir="ltr"
                  >
                    {asset.isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                    {asset.changePercent >= 0 ? '+' : ''}
                    {asset.changePercent.toFixed(2)}%
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="gap-2 bg-[#D4AF37] text-[#0A0A0A] hover:bg-[#C59F2E]"
                    onClick={() => setSelectedAsset(asset.id)}
                  >
                    <BellPlus size={15} />
                    {t.quickAlert[language]}
                  </Button>
                </div>
              </CardHeader>

              <CardContent>
                <div className={`mb-1 text-xs uppercase tracking-wider ${isDark ? 'text-[#A89668]' : 'text-[#8A6A25]'}`}>
                  {activeCurrencyLabel}
                </div>
                <div className={`mb-1 text-3xl font-bold tracking-tight ${isDark ? 'text-[#F5EBCD]' : 'text-[#5A4315]'}`} dir="ltr">
                  {formatPrice(currencyMode === 'usd' ? asset.priceUsd : asset.priceToman, currencyMode, language)}
                </div>
                <div className={`mb-3 text-[11px] ${isDark ? 'text-[#9F8C5D]' : 'text-[#8A6A25]'}`} dir="ltr">
                  USD: {asset.sourceUsd} | Toman: {asset.sourceToman}
                </div>

                <div className={`mb-2 text-xs ${isDark ? 'text-[#A89668]' : 'text-[#8A6A25]'}`}>{t.dragToInspect[language]}</div>

                <div
                  id={`asset-chart-${asset.id}`}
                  className={`relative h-[260px] w-full rounded-xl border p-2 ${
                    isDark ? 'border-[#D4AF37]/15 bg-[#111111]' : 'border-[#D4AF37]/25 bg-[#FFFBF2]'
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
                      <CartesianGrid
                        stroke={isDark ? '#D4AF37' : '#B68A2A'}
                        strokeOpacity={isDark ? 0.12 : 0.18}
                        vertical={false}
                      />
                      <XAxis
                        dataKey="time"
                        tick={{ fill: isDark ? '#AA986A' : '#7A5E24', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        domain={['dataMin', 'dataMax']}
                        tick={{ fill: isDark ? '#AA986A' : '#7A5E24', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        width={56}
                      />
                      <ReferenceLine x={selectedChartPoint.time} stroke={chartColor} strokeOpacity={0.65} strokeDasharray="5 4" />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={chartColor}
                        strokeWidth={3}
                        dot={false}
                        isAnimationActive
                        animationDuration={520}
                        animationEasing="ease-out"
                      />
                    </LineChart>
                  </ResponsiveContainer>

                  {isScrubbingByAsset[asset.id] && tooltipPosition ? (
                    <div
                      className={`pointer-events-none absolute z-20 w-max min-w-[150px] -translate-y-full rounded-lg border px-2 py-1.5 text-[11px] shadow-lg ${
                        isDark
                          ? 'border-[#D4AF37]/30 bg-[#090909]/95 text-[#E8D9AE]'
                          : 'border-[#C79A2B]/40 bg-[#FFF7E6]/95 text-[#6A4D16]'
                      }`}
                      style={{ left: tooltipPosition.x, top: tooltipPosition.y }}
                    >
                      <div>
                        {t.time[language]}: <span className="font-semibold">{selectedChartPoint.time}</span>
                      </div>
                      <div>
                        {t.value[language]}:{' '}
                        <span className="font-semibold">
                          {formatPrice(
                            currencyMode === 'usd' ? selectedPoint.value_usd : selectedPoint.value_toman,
                            currencyMode,
                            language
                          )}
                        </span>
                      </div>
                    </div>
                  ) : null}

                  {asset.chartError ? (
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                      <div
                        className={`rounded-full border px-3 py-1 text-xs font-semibold backdrop-blur-sm ${
                          isDark
                            ? 'border-[#D4AF37]/30 bg-[#000000]/65 text-[#E8D9AE]'
                            : 'border-[#D4AF37]/45 bg-[#FFF4D6]/90 text-[#6B4E16]'
                        }`}
                      >
                        {asset.chartErrorMessage[language] || t.chartUnavailable[language]}
                      </div>
                    </div>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          </motion.div>
        );
      })}

      <Modal isOpen={!!selectedAsset} onClose={closeAlertModal} title={t.createAlertTitle[language]}>
        {selectedAsset && (
          <div className="space-y-5 py-2">
            <div className="flex items-center justify-between rounded-xl bg-slate-50 p-3 dark:bg-white/5">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {cardMap[selectedAsset].label[language]}
              </span>
              <span className="text-sm font-bold text-[#0B1F3A] dark:text-white">
                {formatPrice(
                  currencyMode === 'usd' ? cardMap[selectedAsset].priceUsd : cardMap[selectedAsset].priceToman,
                  currencyMode,
                  language
                )}
              </span>
            </div>

            <div className="space-y-3">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">{t.priceTarget[language]}</label>
              <div className="flex gap-2">
                <Input type="text" placeholder="50,000" className="flex-1 text-center font-bold tracking-wider" dir="ltr" />
                <select className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus-visible:outline-none dark:border-white/10 dark:bg-[#121212] dark:text-white">
                  <option value="above">{t.above[language]}</option>
                  <option value="below">{t.below[language]}</option>
                </select>
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">{t.notifyVia[language]}</label>
              <div className="space-y-2 rounded-xl border border-slate-200 p-3 dark:border-white/10">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-600 dark:text-slate-400">Push Notification (App)</span>
                  <Switch checked={true} onCheckedChange={() => {}} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-600 dark:text-slate-400">SMS / پیامک</span>
                  <Switch checked={false} onCheckedChange={() => {}} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-600 dark:text-slate-400">Telegram / تلگرام</span>
                  <Switch checked={true} onCheckedChange={() => {}} />
                </div>
              </div>
            </div>

            <Button
              variant="primary"
              size="lg"
              className="mt-2 w-full"
              onClick={() => {
                toast.success(language === 'fa' ? 'هشدار با موفقیت ثبت شد' : 'Alert saved successfully');
                closeAlertModal();
              }}
            >
              {t.saveAlert[language]}
            </Button>
          </div>
        )}
      </Modal>

      {loadError ? (
        <div
          className={`rounded-xl border px-3 py-2 text-xs ${
            isDark ? 'border-red-500/30 bg-red-500/10 text-red-200' : 'border-red-400/45 bg-red-100/80 text-red-700'
          }`}
        >
          {loadError}{' '}
          <button type="button" className="underline" onClick={() => window.location.reload()}>
            {t.retry[language]}
          </button>
        </div>
      ) : null}
    </div>
  );
}
