import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { LineChart, Line, ResponsiveContainer, YAxis, XAxis, CartesianGrid, ReferenceLine } from 'recharts';
import { BellPlus, ArrowUpRight, ArrowDownRight, Gem, Coins, GripVertical, Bitcoin, CircleDollarSign, Webhook, Mail, Smartphone, AlertTriangle, Maximize2 } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { useAppContext } from '../context/AppContext';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { toast } from 'sonner';
import { api, formatPrice, getPrices, type CurrencyMode, type PriceAsset } from '../services/api';

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
  btc: { dark: '#F7931A', light: '#D97706' }
};

const STATUS_COLORS = {
  live: { dark: 'bg-emerald-500/10 text-emerald-400', light: 'bg-emerald-100 text-emerald-700' },
  cached: { dark: 'bg-amber-500/10 text-amber-400', light: 'bg-amber-100 text-amber-700' },
  unavailable: { dark: 'bg-red-500/10 text-red-400', light: 'bg-red-100 text-red-700' }
};

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
  change_percent: 0,
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
      chartErrorMessage: placeholder.chart_error_message
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
    usdStatus: asset.usd_status as any,
    tomanStatus: asset.toman_status as any,
    staleMinutes: asset.stale_minutes,
    chartError: asset.chart_error,
    chartErrorMessage: asset.chart_error_message
  };
};

const toChartValue = (point: AssetPoint, mode: CurrencyMode, fallbackValue: number) => {
  const raw = mode === 'usd' ? point.value_usd : point.value_toman;
  return raw ?? fallbackValue;
};

export function DashboardView() {
  const { language, theme, currencyMode, setCurrencyMode } = useAppContext();
  const isDark = theme === 'dark';

  const [assetOrder, setAssetOrder] = useState<AssetId[]>(getInitialAssetOrder);
  const [draggedAssetId, setDraggedAssetId] = useState<AssetId | null>(null);
  const [dragOverAssetId, setDragOverAssetId] = useState<AssetId | null>(null);
  const [isAlertModalOpen, setIsAlertModalOpen] = useState(false);
  const [selectedAssetForAlert, setSelectedAssetForAlert] = useState<AssetId>('gold');
  const [alertTargetPrice, setAlertTargetPrice] = useState('');
  const [alertNotifyApp, setAlertNotifyApp] = useState(true);
  const [alertNotifyEmail, setAlertNotifyEmail] = useState(false);
  const [alertNotifyWebhook, setAlertNotifyWebhook] = useState(false);
  const [alertWebhookUrl, setAlertWebhookUrl] = useState('');
  const [alertEnableDlq, setAlertEnableDlq] = useState(false);
  const [isSavingAlert, setIsSavingAlert] = useState(false);

  const [pricesData, setPricesData] = useState<PriceAsset[]>(EMPTY_ASSETS);
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);
  const [sourceLabel, setSourceLabel] = useState<{ usd: string; toman: string }>({ usd: '...', toman: '...' });
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [activePointIndexByAsset, setActivePointIndexByAsset] = useState<Record<string, number>>({});
  const [isScrubbingByAsset, setIsScrubbingByAsset] = useState<Record<string, boolean>>({});
  const [tooltipPositionByAsset, setTooltipPositionByAsset] = useState<Record<string, TooltipPosition>>({});
  const [fullscreenAsset, setFullscreenAsset] = useState<AssetId | null>(null);

  useEffect(() => {
    window.localStorage.setItem(CHART_ORDER_STORAGE_KEY, JSON.stringify(assetOrder));
  }, [assetOrder]);

  const loadPrices = async () => {
    try {
      setLoadError(null);
      const data = await getPrices();
      setPricesData(data.assets);
      setLastRefreshAt(data.refreshed_at);
      setSourceLabel({ usd: data.source?.usd ?? 'Unknown', toman: data.source?.toman ?? 'Unknown' });
    } catch (err: any) {
      setLoadError(err.message || 'Failed to sync prices');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadPrices();
    const interval = setInterval(loadPrices, 15000);
    return () => clearInterval(interval);
  }, []);

  const orderedAssets = useMemo(() => {
    return assetOrder.map((id) => {
      const live = pricesData.find((a) => a.asset === id);
      return buildLiveCard(live, id, ASSET_ICONS[id]);
    });
  }, [assetOrder, pricesData]);

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
  const usdToTomanRate = (currentUsdt?.priceToman ?? 1) / (currentUsdt?.priceUsd ?? 1);

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

  const statusLabel = (status: 'live' | 'cached' | 'unavailable') => {
    if (status === 'live') {
      return t.live[language];
    }
    if (status === 'cached') {
      return t.cached[language];
    }
    return t.unavailable[language];
  };

  const hasDegradedSources = orderedAssets.some(
    (asset) => asset.usdStatus !== 'live' || asset.tomanStatus !== 'live'
  );

  return (
    <div className="h-full flex flex-col space-y-6">

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>
            {t.currencyView[language]}
          </span>
          <div className={`flex rounded-xl border p-0.5 ${isDark ? 'border-white/10 bg-[#111111]' : 'border-black/10 bg-white'}`}>
            {(['usd', 'toman'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setCurrencyMode(mode)}
                className={`px-4 py-1.5 rounded-[10px] text-xs font-semibold transition-all ${
                  currencyMode === mode
                    ? isDark
                      ? 'bg-[#D4AF37] text-black'
                      : 'bg-[#D4AF37] text-black'
                    : isDark
                      ? 'text-[#A89668] hover:text-white'
                      : 'text-[#7A5E24] hover:text-black'
                }`}
              >
                {mode === 'usd' ? t.usd[language] : t.toman[language]}
              </button>
            ))}
          </div>
        </div>
        {lastRefreshAt && (
          <span className={`text-[11px] ${isDark ? 'text-[#6A5830]' : 'text-[#A8883A]'}`} dir="ltr">
            {t.updatedAt[language]}: {new Date(lastRefreshAt).toLocaleTimeString(language === 'fa' ? 'fa-IR' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        )}
      </div>

      {loadError && (
        <div className={`rounded-2xl border px-4 py-3 text-xs font-medium ${isDark ? 'border-red-500/20 bg-red-500/5 text-red-400' : 'border-red-300 bg-red-50 text-red-700'}`}>
          {language === 'fa' ? `خطا در دریافت قیمت‌ها: ${loadError}` : `Failed to load prices: ${loadError}`}
        </div>
      )}

      {hasDegradedSources && (
        <div className={`rounded-2xl border px-4 py-3 text-xs font-medium ${isDark ? 'border-amber-500/20 bg-amber-500/5 text-amber-400' : 'border-amber-300 bg-amber-50 text-amber-700'}`}>
          {t.degradedNotice[language]}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 min-h-0">
        {orderedAssets.map((asset, idx) => {
        const fallbackValue = currencyMode === 'usd' 
          ? (asset.priceUsd ?? (asset.priceToman ? asset.priceToman / usdToTomanRate : 0)) 
          : (asset.priceToman ?? (asset.priceUsd ? asset.priceUsd * usdToTomanRate : 0));

        const safeHistory = Array.isArray(asset.history) ? asset.history : [];
        const resolvedHistory = safeHistory.length > 0 ? [...safeHistory] : [
          { timestamp: new Date().toISOString(), value_usd: asset.priceUsd, value_toman: asset.priceToman }
        ];

        // Recharts requires at least 2 points to draw a line. If only 1, duplicate it to show a flat line.
        if (resolvedHistory.length === 1) {
            resolvedHistory.unshift({
                ...resolvedHistory[0],
                timestamp: new Date(new Date(resolvedHistory[0].timestamp).getTime() - 60000).toISOString()
            });
        }

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

        const selectedChartPoint = chartData[activeIndex] ?? chartData[chartData.length - 1];
        const chartColor = isDark ? CHART_COLORS[asset.id].dark : CHART_COLORS[asset.id].light;
        const tooltipPosition = tooltipPositionByAsset[asset.id];

        const chartErrorMsg = typeof asset.chartErrorMessage === 'string' 
            ? asset.chartErrorMessage 
            : (asset.chartErrorMessage?.[language] || 'امکان دریافت اطلاعات نمودار وجود ندارد');

        const showChartError = asset.chartError && safeHistory.length === 0 && asset.priceUsd === null && asset.priceToman === null;

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
                      {asset.staleMinutes !== null ? (
                        <span className={`${isDark ? 'text-[#BCA96F]' : 'text-[#7D6023]'}`}>
                          {t.cacheAge[language]}: {asset.staleMinutes} {t.minute[language]}
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
                    {asset.isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                    <span dir="ltr">{Math.abs(asset.changePercent).toFixed(2)}%</span>
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
                
                {showChartError ? (
                  <div className={`flex h-[260px] w-full flex-col items-center justify-center rounded-[1.5rem] border backdrop-blur-md ${
                    isDark ? 'border-red-500/20 bg-[#1A0B0B]/50' : 'border-red-200 bg-[#FFF0F0]/50'
                  }`}>
                    <div className={`text-sm font-semibold ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                      {chartErrorMsg}
                    </div>
                  </div>
                ) : (
                  <>
                    <div className={`mb-2 text-[10px] ${isDark ? 'text-[#887850]' : 'text-[#A8883A]'}`}
                      dir="ltr" title={`USD source: ${asset.sourceUsd}\nToman source: ${asset.sourceToman}`}
                    >
                      USD: {asset.sourceUsd} | Toman: {asset.sourceToman}
                    </div>
                    <div className={`mb-2 text-xs ${isDark ? 'text-[#A89668]' : 'text-[#8A6A25]'}`}>
                      {safeHistory.length <= 1
                        ? (language === 'fa' ? '⏳ در حال جمع‌آوری داده‌های نمودار...' : '⏳ Building chart history...')
                        : t.dragToInspect[language]}
                    </div>
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
          const chartData = resolvedHistory.length === 1 
            ? [resolvedHistory[0], resolvedHistory[0]]
            : resolvedHistory;
          
          const mappedData = chartData.map((point) => ({
            time: new Date(point.timestamp).toLocaleTimeString(language === 'fa' ? 'fa-IR' : 'en-US', { hour: '2-digit', minute: '2-digit' }),
            value: currencyMode === 'usd' 
              ? (point.value_usd ?? (point.value_toman ? point.value_toman / usdToTomanRate : 0))
              : (point.value_toman ?? (point.value_usd ? point.value_usd * usdToTomanRate : 0))
          }));
          
          const chartColor = CHART_COLORS[asset.id][isDark ? 'dark' : 'light'];
          
          return (
            <div className="space-y-4">
              <div className={`text-center text-4xl font-bold ${isDark ? 'text-[#D4AF37]' : 'text-[#8A6B20]'}`}>
                {formatPrice(currencyMode === 'usd' ? asset.priceUsd : asset.priceToman, currencyMode, language)}
              </div>
              <div 
                className={`h-[60vh] w-full rounded-2xl border p-4 ${isDark ? 'border-white/5 bg-[#111111]/40' : 'border-black/5 bg-white/40'}`}
                dir="ltr"
              >
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={mappedData}>
                    <CartesianGrid stroke={isDark ? '#D4AF37' : '#B68A2A'} strokeOpacity={isDark ? 0.12 : 0.18} vertical={false} />
                    <XAxis dataKey="time" tick={{ fill: isDark ? '#AA986A' : '#7A5E24', fontSize: 12 }} axisLine={false} tickLine={false} />
                    <YAxis domain={['dataMin', 'dataMax']} tick={{ fill: isDark ? '#AA986A' : '#7A5E24', fontSize: 12 }} axisLine={false} tickLine={false} width={70} />
                    <Line type="monotone" dataKey="value" stroke={chartColor} strokeWidth={3} dot={false} activeDot={{ r: 7, fill: chartColor, stroke: isDark ? '#0A0A0A' : '#FFFFFF', strokeWidth: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className={`text-center text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                USD: {asset.sourceUsd} | Toman: {asset.sourceToman}
              </div>
            </div>
          );
        })()}
      </Modal>
    </div>
  );
}
