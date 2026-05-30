import React, { useState } from 'react';
import { motion } from 'motion/react';
import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';
import { BellPlus, TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight, DollarSign, Coins, CircleDollarSign, Gem } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { useAppContext } from '../context/AppContext';
import { Modal } from '../components/ui/Modal';
import { Input } from '../components/ui/Input';
import { Switch } from '../components/ui/Switch';

import { toast } from 'sonner';

const generateData = (start: number, volatility: number, trend: number) => {
  let current = start;
  return Array.from({ length: 20 }, (_, i) => {
    current += (Math.random() - 0.5) * volatility + trend;
    return { value: current };
  });
};

const ASSETS = [
  {
    id: 'gold',
    name: { fa: 'طلا (۱۸ عیار)', en: 'Gold (18k)' },
    price: { fa: '۳,۴۵۰,۰۰۰ تومان', en: '3,450,000 T' },
    change: '+1.2%',
    isUp: true,
    icon: Gem,
    data: generateData(3400, 20, 1),
  },
  {
    id: 'usd',
    name: { fa: 'دلار آمریکا', en: 'US Dollar' },
    price: { fa: '۵۹,۲۰۰ تومان', en: '59,200 T' },
    change: '-0.5%',
    isUp: false,
    icon: DollarSign,
    data: generateData(5950, 10, -1),
  },
  {
    id: 'btc',
    name: { fa: 'بیت‌کوین', en: 'Bitcoin' },
    price: { fa: '۶۴,۲۳۰ دلار', en: '$64,230' },
    change: '+3.4%',
    isUp: true,
    icon: CircleDollarSign,
    data: generateData(62000, 500, 100),
  },
  {
    id: 'silver',
    name: { fa: 'نقره', en: 'Silver' },
    price: { fa: '۵۴,۰۰۰ تومان', en: '54,000 T' },
    change: '+0.8%',
    isUp: true,
    icon: Coins,
    data: generateData(5300, 30, 0.5),
  },
];

export function DashboardView() {
  const { language } = useAppContext();
  const [selectedAsset, setSelectedAsset] = useState<string | null>(null);
  
  const closeAlertModal = () => setSelectedAsset(null);

  const t = {
    quickAlert: { fa: 'هشدار سریع', en: 'Quick Alert' },
    createAlertTitle: { fa: 'ایجاد هشدار جدید', en: 'Create New Alert' },
    priceTarget: { fa: 'قیمت هدف', en: 'Target Price' },
    condition: { fa: 'شرط', en: 'Condition' },
    above: { fa: 'بالاتر از', en: 'Above' },
    below: { fa: 'پایین‌تر از', en: 'Below' },
    notifyVia: { fa: 'اطلاع‌رسانی از طریق', en: 'Notify via' },
    saveAlert: { fa: 'ثبت هشدار', en: 'Save Alert' },
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        {ASSETS.map((asset, idx) => (
          <motion.div
            key={asset.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.1 }}
          >
            <Card className="group relative overflow-hidden transition-all hover:shadow-md dark:hover:border-white/20">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="flex items-center gap-2 text-sm font-medium text-slate-500 dark:text-slate-400">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700 dark:bg-white/5 dark:text-slate-300">
                    <asset.icon size={16} />
                  </div>
                  {asset.name[language]}
                </CardTitle>
                <div
                  className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${
                    asset.isUp
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400'
                      : 'bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400'
                  }`}
                  dir="ltr"
                >
                  {asset.isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                  {asset.change}
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold tracking-tight text-[#0B1F3A] dark:text-white mt-1">
                  {asset.price[language]}
                </div>
                
                <div className="mt-4 h-[60px] w-full" dir="ltr">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={asset.data}>
                      <YAxis domain={['dataMin', 'dataMax']} hide />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={asset.isUp ? '#10B981' : '#EF4444'}
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>

                <div className="mt-4 opacity-0 transition-opacity group-hover:opacity-100">
                  <Button
                    variant="secondary"
                    size="sm"
                    className="w-full gap-2"
                    onClick={() => setSelectedAsset(asset.id)}
                  >
                    <BellPlus size={16} />
                    {t.quickAlert[language]}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      <Modal isOpen={!!selectedAsset} onClose={closeAlertModal} title={t.createAlertTitle[language]}>
        {selectedAsset && (
          <div className="space-y-5 py-2">
            <div className="flex items-center justify-between rounded-xl bg-slate-50 p-3 dark:bg-white/5">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {ASSETS.find(a => a.id === selectedAsset)?.name[language]}
              </span>
              <span className="text-sm font-bold text-[#0B1F3A] dark:text-white">
                {ASSETS.find(a => a.id === selectedAsset)?.price[language]}
              </span>
            </div>

            <div className="space-y-3">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {t.priceTarget[language]}
              </label>
              <div className="flex gap-2">
                <Input type="text" placeholder="50,000" className="flex-1 text-center font-bold tracking-wider" dir="ltr" />
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

            <Button variant="primary" size="lg" className="w-full mt-2" onClick={() => {
              toast.success(language === 'fa' ? 'هشدار با موفقیت ثبت شد' : 'Alert saved successfully');
              closeAlertModal();
            }}>
              {t.saveAlert[language]}
            </Button>
          </div>
        )}
      </Modal>
    </div>
  );
}
