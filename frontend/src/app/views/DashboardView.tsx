import React, { useMemo, useState } from 'react';
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
  DollarSign,
  Coins,
  CircleDollarSign,
  Gem
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { useAppContext } from '../context/AppContext';
import { Modal } from '../components/ui/Modal';
import { Input } from '../components/ui/input';
import { Switch } from '../components/ui/switch';
import { toast } from 'sonner';

type DataPoint = {
  time: string;
  value: number;
};

type Asset = {
  id: string;
  name: { fa: string; en: string };
  price: { fa: string; en: string };
  change: string;
  isUp: boolean;
  icon: LucideIcon;
  data: DataPoint[];
};

const generateData = (start: number, volatility: number, trend: number) => {
  let current = start;
  return Array.from({ length: 24 }, (_, i) => {
    current += (Math.random() - 0.5) * volatility + trend;
    return {
      time: `${String(i).padStart(2, '0')}:00`,
      value: Number(current.toFixed(2))
    };
  });
};

const ASSETS: Asset[] = [
  {
    id: 'gold',
    name: { fa: 'طلا (۱۸ عیار)', en: 'Gold (18k)' },
    price: { fa: '۳,۴۵۰,۰۰۰ تومان', en: '3,450,000 T' },
    change: '+1.2%',
    isUp: true,
    icon: Gem,
    data: generateData(3400, 25, 1.3)
  },
  {
    id: 'usd',
    name: { fa: 'دلار آمریکا', en: 'US Dollar' },
    price: { fa: '۵۹,۲۰۰ تومان', en: '59,200 T' },
    change: '-0.5%',
    isUp: false,
    icon: DollarSign,
    data: generateData(5950, 14, -0.6)
  },
  {
    id: 'btc',
    name: { fa: 'بیت‌کوین', en: 'Bitcoin' },
    price: { fa: '۶۴,۲۳۰ دلار', en: '$64,230' },
    change: '+3.4%',
    isUp: true,
    icon: CircleDollarSign,
    data: generateData(62000, 800, 120)
  },
  {
    id: 'silver',
    name: { fa: 'نقره', en: 'Silver' },
    price: { fa: '۵۴,۰۰۰ تومان', en: '54,000 T' },
    change: '+0.8%',
    isUp: true,
    icon: Coins,
    data: generateData(5300, 38, 0.9)
  }
];

export function DashboardView() {
  const { language } = useAppContext();
  const [selectedAsset, setSelectedAsset] = useState<string | null>(null);
  const [assetOrder, setAssetOrder] = useState<string[]>(ASSETS.map((asset) => asset.id));
  const [draggedAssetId, setDraggedAssetId] = useState<string | null>(null);
  const [activePointIndexByAsset, setActivePointIndexByAsset] = useState<Record<string, number>>({});
  const [isScrubbingByAsset, setIsScrubbingByAsset] = useState<Record<string, boolean>>({});

  const orderedAssets = useMemo(
    () => assetOrder.map((id) => ASSETS.find((asset) => asset.id === id)).filter(Boolean) as Asset[],
    [assetOrder]
  );

  const closeAlertModal = () => setSelectedAsset(null);

  const t = {
    quickAlert: { fa: 'هشدار سریع', en: 'Quick Alert' },
    dragToReorder: { fa: 'برای جابجایی بکشید', en: 'Drag to reorder' },
    dragToInspect: { fa: 'برای دیدن قیمت در زمان‌های مختلف روی نمودار بکشید', en: 'Drag on the chart to inspect prices over time' },
    createAlertTitle: { fa: 'ایجاد هشدار جدید', en: 'Create New Alert' },
    priceTarget: { fa: 'قیمت هدف', en: 'Target Price' },
    notifyVia: { fa: 'اطلاع‌رسانی از طریق', en: 'Notify via' },
    above: { fa: 'بالاتر از', en: 'Above' },
    below: { fa: 'پایین‌تر از', en: 'Below' },
    saveAlert: { fa: 'ثبت هشدار', en: 'Save Alert' },
    selectedPoint: { fa: 'نقطه انتخاب‌شده', en: 'Selected Point' },
    time: { fa: 'زمان', en: 'Time' },
    value: { fa: 'قیمت', en: 'Price' }
  };

  const reorderAssets = (fromId: string, toId: string) => {
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

  const updateScrubPoint = (asset: Asset, clientX: number) => {
    const chartElement = document.getElementById(`asset-chart-${asset.id}`);
    if (!chartElement) {
      return;
    }

    const rect = chartElement.getBoundingClientRect();
    const ratio = (clientX - rect.left) / rect.width;
    const clampedRatio = Math.max(0, Math.min(1, ratio));
    const index = Math.round(clampedRatio * (asset.data.length - 1));
    setActivePointIndexByAsset((prev) => ({ ...prev, [asset.id]: index }));
  };

  return (
    <div className="space-y-6">
      {orderedAssets.map((asset, idx) => {
        const activeIndex = activePointIndexByAsset[asset.id] ?? asset.data.length - 1;
        const selectedPoint = asset.data[activeIndex];

        return (
          <motion.div
            key={asset.id}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.05, duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            draggable
            onDragStart={() => setDraggedAssetId(asset.id)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (draggedAssetId) {
                reorderAssets(draggedAssetId, asset.id);
                setDraggedAssetId(null);
              }
            }}
            onDragEnd={() => setDraggedAssetId(null)}
            className="cursor-grab active:cursor-grabbing"
          >
            <Card className="relative overflow-hidden border-[#D4AF37]/20 bg-[#0E0E0E]/95 shadow-[0_12px_36px_rgba(0,0,0,0.35)]">
              <CardHeader className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base font-semibold text-[#E8D9AE]">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#D4AF37] text-[#0A0A0A]">
                      <asset.icon size={18} />
                    </div>
                    {asset.name[language]}
                  </CardTitle>
                  <p className="mt-1 text-xs text-[#A89668]">{t.dragToReorder[language]}</p>
                </div>

                <div className="flex items-center gap-3">
                  <div
                    className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
                      asset.isUp
                        ? 'bg-emerald-500/15 text-emerald-300'
                        : 'bg-red-500/15 text-red-300'
                    }`}
                    dir="ltr"
                  >
                    {asset.isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                    {asset.change}
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
                <div className="mb-3 text-3xl font-bold tracking-tight text-[#F5EBCD]">
                  {asset.price[language]}
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
                    <LineChart data={asset.data}>
                      <CartesianGrid stroke="#D4AF37" strokeOpacity={0.12} vertical={false} />
                      <XAxis dataKey="time" tick={{ fill: '#AA986A', fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis
                        domain={['dataMin', 'dataMax']}
                        tick={{ fill: '#AA986A', fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        width={56}
                      />
                      <ReferenceLine x={selectedPoint.time} stroke="#E4C766" strokeDasharray="5 4" />
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
                  {t.time[language]} <span className="text-[#F5EBCD]">{selectedPoint.time}</span> - {t.value[language]}{' '}
                  <span className="text-[#F5EBCD]">{selectedPoint.value.toLocaleString()}</span>
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
                {ASSETS.find((asset) => asset.id === selectedAsset)?.name[language]}
              </span>
              <span className="text-sm font-bold text-[#0B1F3A] dark:text-white">
                {ASSETS.find((asset) => asset.id === selectedAsset)?.price[language]}
              </span>
            </div>

            <div className="space-y-3">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {t.priceTarget[language]}
              </label>
              <div className="flex gap-2">
                <Input
                  type="text"
                  placeholder="50,000"
                  className="flex-1 text-center font-bold tracking-wider"
                  dir="ltr"
                />
                <select className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus-visible:outline-none dark:border-white/10 dark:bg-[#121212] dark:text-white">
                  <option value="above">{t.above[language]}</option>
                  <option value="below">{t.below[language]}</option>
                </select>
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {t.notifyVia[language]}
              </label>
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
