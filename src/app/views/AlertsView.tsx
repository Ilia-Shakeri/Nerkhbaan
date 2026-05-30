import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { BellRing, BellOff, Pencil, Trash2, ArrowUpRight, ArrowDownRight, Search } from 'lucide-react';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Switch } from '../components/ui/switch';
import { Input } from '../components/ui/input';
import { useAppContext } from '../context/AppContext';

type Alert = {
  id: string;
  asset: string;
  assetFa: string;
  target: string;
  condition: 'above' | 'below';
  active: boolean;
};

const INITIAL_ALERTS: Alert[] = [
  { id: '1', asset: 'Gold', assetFa: 'طلا', target: '3,500,000 T', condition: 'above', active: true },
  { id: '2', asset: 'Bitcoin', assetFa: 'بیت‌کوین', target: '$60,000', condition: 'below', active: false },
  { id: '3', asset: 'USD', assetFa: 'دلار', target: '60,000 T', condition: 'above', active: true },
];

export function AlertsView() {
  const { language } = useAppContext();
  const [alerts, setAlerts] = useState<Alert[]>(INITIAL_ALERTS);

  const t = {
    search: { fa: 'جستجوی هشدار...', en: 'Search alerts...' },
    newAlert: { fa: 'هشدار جدید', en: 'New Alert' },
    asset: { fa: 'دارایی', en: 'Asset' },
    condition: { fa: 'وضعیت', en: 'Condition' },
    target: { fa: 'قیمت هدف', en: 'Target' },
    status: { fa: 'وضعیت', en: 'Status' },
    actions: { fa: 'عملیات', en: 'Actions' },
    above: { fa: 'بیشتر از', en: 'Above' },
    below: { fa: 'کمتر از', en: 'Below' },
    active: { fa: 'فعال', en: 'Active' },
    inactive: { fa: 'غیرفعال', en: 'Inactive' },
  };

  const toggleAlert = (id: string) => {
    setAlerts(alerts.map(a => a.id === id ? { ...a, active: !a.active } : a));
  };

  const deleteAlert = (id: string) => {
    setAlerts(alerts.filter(a => a.id !== id));
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      
      {/* Header / Actions */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <Input 
            placeholder={t.search[language]} 
            className="ps-10"
          />
        </div>
        
        <Button variant="primary" className="gap-2 shrink-0">
          <BellRing size={18} />
          {t.newAlert[language]}
        </Button>
      </div>

      {/* Alerts List (Desktop Table Style / Mobile Card Style) */}
      <div className="grid gap-4">
        <AnimatePresence>
          {alerts.map((alert) => (
            <motion.div
              key={alert.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              layout
            >
              <Card className={`group flex flex-col sm:flex-row items-start sm:items-center justify-between p-4 transition-all hover:shadow-md ${!alert.active ? 'opacity-60 grayscale' : ''}`}>
                
                {/* Info Block */}
                <div className="flex flex-1 items-center gap-4 w-full">
                  <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${
                    alert.active 
                      ? 'bg-blue-50 text-[#0B1F3A] dark:bg-blue-500/10 dark:text-blue-400' 
                      : 'bg-slate-100 text-slate-400 dark:bg-white/5 dark:text-slate-500'
                  }`}>
                    {alert.active ? <BellRing size={22} /> : <BellOff size={22} />}
                  </div>
                  
                  <div className="flex flex-1 flex-col gap-1 sm:flex-row sm:items-center sm:gap-6">
                    <div className="min-w-[120px]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">{t.asset[language]}</div>
                      <div className="font-bold text-[#0B1F3A] dark:text-white text-lg">
                        {language === 'fa' ? alert.assetFa : alert.asset}
                      </div>
                    </div>

                    <div className="hidden sm:block h-8 w-[1px] bg-slate-200 dark:bg-white/10" />

                    <div className="min-w-[100px]">
                      <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">{t.condition[language]}</div>
                      <div className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        alert.condition === 'above' 
                          ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400' 
                          : 'bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400'
                      }`} dir="ltr">
                        {alert.condition === 'above' ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                        {alert.condition === 'above' ? t.above[language] : t.below[language]}
                      </div>
                    </div>

                    <div className="hidden sm:block h-8 w-[1px] bg-slate-200 dark:bg-white/10" />

                    <div className="min-w-[120px]">
                      <div className="text-xs text-slate-500 dark:text-slate-400">{t.target[language]}</div>
                      <div className="font-bold tracking-wider text-slate-900 dark:text-slate-100 font-sans" dir="ltr">
                        {alert.target}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Actions Block */}
                <div className="mt-4 flex w-full items-center justify-between border-t border-slate-100 pt-4 sm:mt-0 sm:w-auto sm:border-t-0 sm:pt-0 dark:border-white/5">
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={alert.active}
                      onCheckedChange={() => toggleAlert(alert.id)}
                    />
                    <span className="text-sm font-medium text-slate-600 dark:text-slate-400 w-16 text-start">
                      {alert.active ? t.active[language] : t.inactive[language]}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 border-s border-slate-200 ps-4 ms-4 dark:border-white/10">
                    <Button variant="ghost" size="icon" className="h-9 w-9 text-slate-500 hover:text-[#0B1F3A] dark:hover:text-white">
                      <Pencil size={18} />
                    </Button>
                    <Button 
                      variant="ghost" 
                      size="icon" 
                      className="h-9 w-9 text-slate-500 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10 dark:hover:text-red-400"
                      onClick={() => deleteAlert(alert.id)}
                    >
                      <Trash2 size={18} />
                    </Button>
                  </div>
                </div>

              </Card>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

    </div>
  );
}
