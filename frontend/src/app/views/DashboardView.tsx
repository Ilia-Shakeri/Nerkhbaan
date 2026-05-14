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
import { BellPlus, ArrowUpRight, ArrowDownRight, Gem, Coins, GripVertical } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { useAppContext } from '../context/AppContext';
import { Modal } from '../components/ui/Modal';
import { Input } from '../components/ui/input';
import { Switch } from '../components/ui/switch';
import { toast } from 'sonner';
import { formatPrice, getPrices, type CurrencyMode, type PriceAsset } from '../services/api';

type AssetCard = {
  id: 'gold' | 'silver';
  label: { fa: string; en: string };
  icon: LucideIcon;
  priceUsd: number;
  priceToman: number;
  changePercent: number;
  isUp: boolean;
  history: Array<{
    timestamp: string;
    value_usd: number;
    value_toman: number;
  }>;
};

const CHART_ORDER_STORAGE_KEY = 'dashboard-chart-order-v2';
const DEFAULT_ASSET_ORDER: Array<'gold' | 'silver'> = ['gold', 'silver'];

const getInitialAssetOrder = (): Array<'gold' | 'silver'> => {
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
      (value): value is 'gold' | 'silver' => typeof value === 'string' && validIds.has(value as 'gold' | 'silver')
    );
    const missingIds = DEFAULT_ASSET_ORDER.filter((id) => !savedIds.includes(id));
    return [...savedIds, ...missingIds];
  } catch {
    return DEFAULT_ASSET_ORDER;
  }
};

export function DashboardView() {
  const { language } = useAppContext();
  const [selectedAsset, setSelectedAsset] = useState<'gold' | 'silver' | null>(null);
  const [assetOrder, setAssetOrder] = useState<Array<'gold' | 'silver'>>(getInitialAssetOrder);
  const [draggedAssetId, setDraggedAssetId] = useState<'gold' | 'silver' | null>(null);
  const [dragOverAssetId, setDragOverAssetId] = useState<'gold' | 'silver' | null>(null);
  const [activePointIndexByAsset, setActivePointIndexByAsset] = useState<Record<string, number>>({});
  const [isScrubbingByAsset, setIsScrubbingByAsset] = useState<Record<string, boolean>>({});

  const [currencyMode, setCurrencyMode] = useState<CurrencyMode>('usd');
  const [assets, setAssets] = useState<PriceAsset[]>([]);
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
        if (isMounted && assets.length === 0) {
          setIsLoading(true);
        }

        const response = await getPrices();
        if (!isMounted) {
          return;
        }

        setAssets(response.assets);
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
  }, [assets.length]);

  const t = {
    quickAlert: { fa: 'هشدار سریع', en: 'Quick Alert' },
    dragToReorder: { fa: 'برای جابجایی بکشید', en: 'Drag to reorder' },
    dragToInspect: {
      fa: 'برای دیدن قیمت در زمان‌های مختلف روی نمودار بکشید',
      en: 'Drag on the chart to inspect prices over time'
    },
    createAlertTitle: { fa: 'ایجاد هشدار جدید', en: 'Create New Alert' },
    priceTarget: { fa: 'قیمت هدف', en: 'Target Price' },
    notifyVia: { fa: 'اطلاع‌رسانی از طریق', en: 'Notify via' },
    above: { fa: 'بالاتر از', en: 'Above' },
    below: { fa: 'پایین‌تر از', en: 'Below' },
    saveAlert: { fa: 'ثبت هشدار', en: 'Save Alert' },
    selectedPoint: { fa: 'نقطه انتخاب‌شده', en: 'Selected Point' },
    time: { fa: 'زمان', en: 'Time' },
    value: { fa: 'قیمت', en: 'Price' },
    usd: { fa: 'دلار', en: 'USD' },
    toman: { fa: 'تومان', en: 'Toman' },
    currencyView: { fa: 'نمایش قیمت', en: 'Currency View' },
    source: { fa: 'منبع', en: 'Source' },
    updatedAt: { fa: 'آخرین بروزرسانی', en: 'Last update' },
    loading: { fa: 'در حال دریافت قیمت ها...', en: 'Loading live prices...' },
    retry: { fa: 'تلاش مجدد', en: 'Retry' }
  };

  const cardMap: Record<'gold' | 'silver', AssetCard> = useMemo(() => {
    const toCard = (asset: PriceAsset): AssetCard => ({
      id: asset.asset,
      label: {
        fa: asset.label_fa,
        en: asset.label_en
      },
      icon: asset.asset === 'gold' ? Gem : Coins,
      priceUsd: asset.price_usd,
      priceToman: asset.price_toman,
      changePercent: asset.change_percent,
      isUp: asset.trend === 'up',
      history: asset.history
    });

    const defaultCard = (id: 'gold' | 'silver', labelFa: string, labelEn: string, icon: LucideIcon): AssetCard => ({
      id,
      label: { fa: labelFa, en: labelEn },
      icon,
      priceUsd: 0,
      priceToman: 0,
      changePercent: 0,
      isUp: true,
      history: []
    });

    const goldAsset = assets.find((asset) => asset.asset === 'gold');
    const silverAsset = assets.find((asset) => asset.asset === 'silver');

    return {
      gold: goldAsset ? toCard(goldAsset) : defaultCard('gold', 'طلا', 'Gold', Gem),
      silver: silverAsset ? toCard(silverAsset) : defaultCard('silver', 'نقره', 'Silver', Coins)
    };
  }, [assets]);

  const orderedAssets = useMemo(() => assetOrder.map((id) => cardMap[id]), [assetOrder, cardMap]);

  const reorderAssets = (fromId: 'gold' | 'silver', toId: 'gold' | 'silver') => {
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

  const updateScrubPoint = (asset: AssetCard, clientX: number) => {
    const chartElement = document.getElementById(`asset-chart-${asset.id}`);
    if (!chartElement || asset.history.length === 0) {
      return;
    }

    const rect = chartElement.getBoundingClientRect();
    const ratio = (clientX - rect.left) / rect.width;
    const clampedRatio = Math.max(0, Math.min(1, ratio));
    const index = Math.round(clampedRatio * (asset.history.length - 1));
    setActivePointIndexByAsset((prev) => ({ ...prev, [asset.id]: index }));
  };

  if (isLoading && assets.length === 0) {
    return <div className="text-sm text-[#B7A372]">{t.loading[language]}</div>;
  }

  if (loadError && assets.length === 0) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
        <p>{loadError}</p>
        <Button className="mt-3" onClick={() => window.location.reload()}>
          {t.retry[language]}
        </Button>
      </div>
    );
  }

  const activeCurrencyLabel = currencyMode === 'usd' ? t.usd[language] : t.toman[language];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#D4AF37]/20 bg-[#0E0E0E]/80 p-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[#CDBB8C]">{t.currencyView[language]}</span>
          <div className="rounded-xl border border-[#D4AF37]/20 bg-[#111111] p-1">
            <button
              type="button"
              onClick={() => setCurrencyMode('usd')}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                currencyMode === 'usd' ? 'bg-[#D4AF37] text-[#0A0A0A]' : 'text-[#CDBB8C]'
              }`}
            >
              {t.usd[language]}
            </button>
            <button
              type="button"
              onClick={() => setCurrencyMode('toman')}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                currencyMode === 'toman' ? 'bg-[#D4AF37] text-[#0A0A0A]' : 'text-[#CDBB8C]'
              }`}
            >
              {t.toman[language]}
            </button>
          </div>
        </div>

        <div className="text-xs text-[#A89668]" dir="ltr">
          {t.source[language]}: USD={sourceLabel.usd} | Toman={sourceLabel.toman}
          {lastRefreshAt ? ` | ${t.updatedAt[language]}: ${new Date(lastRefreshAt).toLocaleTimeString()}` : ''}
          {loadError ? ` | ${loadError}` : ''}
        </div>
      </div>

      {orderedAssets.map((asset, idx) => {
        const activeIndex = Math.min(
          activePointIndexByAsset[asset.id] ?? Math.max(asset.history.length - 1, 0),
          Math.max(asset.history.length - 1, 0)
        );

        const selectedPoint = asset.history[activeIndex] ?? {
          timestamp: new Date().toISOString(),
          value_usd: asset.priceUsd,
          value_toman: asset.priceToman
        };

        const chartData = asset.history.length
          ? asset.history.map((point) => ({
              time: new Date(point.timestamp).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit'
              }),
              value: currencyMode === 'usd' ? point.value_usd : point.value_toman
            }))
          : [
              {
                time: '--:--',
                value: currencyMode === 'usd' ? asset.priceUsd : asset.priceToman
              }
            ];

        const selectedChartPoint = chartData[activeIndex] ?? chartData[chartData.length - 1];

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
              layout: { type: 'spring', damping: 30, stiffness: 360 }
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
              className={`relative overflow-hidden border-[#D4AF37]/20 bg-[#0E0E0E]/95 shadow-[0_12px_36px_rgba(0,0,0,0.35)] transition-all duration-200 ${
                dragOverAssetId === asset.id
                  ? 'ring-1 ring-[#D4AF37]/45 shadow-[0_0_0_1px_rgba(212,175,55,0.18),0_12px_36px_rgba(0,0,0,0.35)]'
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
                    className="mt-1 inline-flex h-8 w-8 shrink-0 cursor-grab items-center justify-center rounded-md border border-[#D4AF37]/30 text-[#D4AF37] transition hover:bg-[#D4AF37]/10 active:cursor-grabbing"
                    aria-label={t.dragToReorder[language]}
                    title={t.dragToReorder[language]}
                  >
                    <GripVertical size={16} />
                  </button>
                  <div>
                    <CardTitle className="flex items-center gap-2 text-base font-semibold text-[#E8D9AE]">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#D4AF37] text-[#0A0A0A]">
                        <asset.icon size={18} />
                      </div>
                      {asset.label[language]}
                    </CardTitle>
                    <p className="mt-1 text-xs text-[#A89668]">{t.dragToReorder[language]}</p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div
                    className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
                      asset.isUp ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'
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
                <div className="mb-1 text-xs uppercase tracking-wider text-[#A89668]">{activeCurrencyLabel}</div>
                <div className="mb-3 text-3xl font-bold tracking-tight text-[#F5EBCD]" dir="ltr">
                  {formatPrice(
                    currencyMode === 'usd' ? asset.priceUsd : asset.priceToman,
                    currencyMode,
                    language
                  )}
                </div>

                <div className="mb-2 text-xs text-[#A89668]">{t.dragToInspect[language]}</div>

                <div
                  id={`asset-chart-${asset.id}`}
                  className="h-[260px] w-full rounded-xl border border-[#D4AF37]/15 bg-[#111111] p-2"
                  dir="ltr"
                  onMouseDown={(event) => {
                    setIsScrubbingByAsset((prev) => ({ ...prev, [asset.id]: true }));
                    updateScrubPoint(asset, event.clientX);
                  }}
                  onMouseMove={(event) => {
                    if (isScrubbingByAsset[asset.id]) {
                      updateScrubPoint(asset, event.clientX);
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
                      <CartesianGrid stroke="#D4AF37" strokeOpacity={0.12} vertical={false} />
                      <XAxis dataKey="time" tick={{ fill: '#AA986A', fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis
                        domain={['dataMin', 'dataMax']}
                        tick={{ fill: '#AA986A', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        width={56}
                      />
                      <ReferenceLine x={selectedChartPoint.time} stroke="#E4C766" strokeDasharray="5 4" />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={asset.isUp ? '#10B981' : '#EF4444'}
                        strokeWidth={3}
                        dot={false}
                        isAnimationActive
                        animationDuration={520}
                        animationEasing="ease-out"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>

                <div className="mt-3 rounded-lg border border-[#D4AF37]/15 bg-[#0B0B0B] px-3 py-2 text-xs text-[#CDBB8C]">
                  <span className="font-semibold">{t.selectedPoint[language]}: </span>
                  {t.time[language]} <span className="text-[#F5EBCD]">{selectedChartPoint.time}</span> - {t.value[language]}{' '}
                  <span className="text-[#F5EBCD]">
                    {formatPrice(
                      currencyMode === 'usd' ? selectedPoint.value_usd : selectedPoint.value_toman,
                      currencyMode,
                      language
                    )}
                  </span>
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
    </div>
  );
}
