import React, { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowDownRight, ArrowUpRight, BellOff, BellRing, Loader2, Plus, Search, Trash2 } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { toast } from 'sonner';
import { useAppContext } from '../context/AppContext';
import { api, type AlertResponse, type CurrencyMode } from '../services/api';

const labels: Record<string, { fa: string; en: string }> = {
  gold: { fa: 'طلا', en: 'Gold' },
  silver: { fa: 'نقره', en: 'Silver' },
  usdt: { fa: 'تتر', en: 'Tether' },
  btc: { fa: 'بیت‌کوین', en: 'Bitcoin' },
};

export function AlertsView() {
  const { language, theme, currencyMode } = useAppContext();
  const isDark = theme === 'dark';
  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [asset, setAsset] = useState('gold');
  const [condition, setCondition] = useState<'above' | 'below'>('above');
  const [target, setTarget] = useState('');
  const [mode, setMode] = useState<CurrencyMode>(currencyMode);
  const [notifyApp, setNotifyApp] = useState(true);
  const [notifyEmail, setNotifyEmail] = useState(false);

  const t = {
    search: { fa: 'جستجوی هشدار...', en: 'Search alerts...' },
    newAlert: { fa: 'هشدار جدید', en: 'New Alert' },
    noAlerts: { fa: 'هشداری ثبت نشده است', en: 'No alerts yet' },
    above: { fa: 'بیشتر از', en: 'Above' },
    below: { fa: 'کمتر از', en: 'Below' },
    active: { fa: 'فعال', en: 'Active' },
    inactive: { fa: 'غیرفعال', en: 'Inactive' },
    target: { fa: 'قیمت هدف', en: 'Target price' },
    asset: { fa: 'دارایی', en: 'Asset' },
    currency: { fa: 'واحد', en: 'Currency' },
    app: { fa: 'اعلان درون برنامه', en: 'In-app notification' },
    email: { fa: 'ایمیل', en: 'Email' },
    create: { fa: 'ایجاد هشدار', en: 'Create alert' },
    cancel: { fa: 'انصراف', en: 'Cancel' },
  };

  useEffect(() => {
    let active = true;
    api.alerts.list()
      .then((items) => {
        if (active) setAlerts(items);
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : 'Failed to load alerts'))
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => alerts.filter((item) => {
    const name = labels[item.asset]?.[language] ?? item.asset;
    return name.toLocaleLowerCase().includes(query.toLocaleLowerCase());
  }), [alerts, language, query]);

  const removeAlert = async (id: number) => {
    try {
      await api.alerts.remove(id);
      setAlerts((current) => current.filter((item) => item.id !== id));
      toast.success(language === 'fa' ? 'هشدار حذف شد' : 'Alert removed');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to remove alert');
    }
  };

  const createAlert = async () => {
    const targetPrice = Number(target);
    if (!Number.isFinite(targetPrice) || targetPrice <= 0) return;
    setIsSaving(true);
    try {
      const created = await api.alerts.create({
        asset,
        target_price: targetPrice,
        alert_type: 'price',
        formula: null,
        currency_mode: mode,
        condition,
        notify_app: notifyApp,
        notify_email: notifyEmail,
        notify_webhook: false,
        webhook_url: null,
        enable_dlq: false,
      });
      setAlerts((current) => [created, ...current]);
      setTarget('');
      setIsModalOpen(false);
      toast.success(language === 'fa' ? 'هشدار ایجاد شد' : 'Alert created');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to create alert');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t.search[language]} className="ps-10" />
        </div>
        <Button variant="primary" className="shrink-0 gap-2" onClick={() => setIsModalOpen(true)}>
          <Plus size={18} />{t.newAlert[language]}
        </Button>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center"><Loader2 className="animate-spin text-[#D4AF37]" size={28} /></div>
      ) : filtered.length === 0 ? (
        <Card className="flex min-h-48 flex-col items-center justify-center gap-3 p-8 text-center">
          <BellOff className="text-[#D4AF37]" size={40} />
          <span className="font-semibold text-slate-500 dark:text-slate-300">{t.noAlerts[language]}</span>
        </Card>
      ) : (
        <div className="grid gap-4">
          <AnimatePresence>
            {filtered.map((item) => (
              <motion.div key={item.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }} layout>
                <Card className={`flex flex-col items-start justify-between gap-4 p-4 sm:flex-row sm:items-center ${!item.is_active ? 'opacity-60 grayscale' : ''}`}>
                  <div className="flex items-center gap-4">
                    <div className={`flex h-12 w-12 items-center justify-center rounded-2xl ${item.is_active ? 'bg-[#D4AF37]/15 text-[#D4AF37]' : 'bg-slate-100 text-slate-400 dark:bg-white/5'}`}>
                      {item.is_active ? <BellRing size={22} /> : <BellOff size={22} />}
                    </div>
                    <div className="space-y-1">
                      <div className="text-lg font-bold text-[#0B1F3A] dark:text-white">{labels[item.asset]?.[language] ?? item.asset}</div>
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${item.condition === 'above' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500'}`}>
                          {item.condition === 'above' ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                          {t[item.condition][language]}
                        </span>
                        <span className="font-bold" dir="ltr">{item.target_price?.toLocaleString() ?? item.formula ?? '--'} {item.currency_mode === 'usd' ? 'USD' : 'TMN'}</span>
                        <span className="text-slate-500">{item.is_active ? t.active[language] : t.inactive[language]}</span>
                      </div>
                    </div>
                  </div>
                  <Button variant="ghost" size="icon" onClick={() => void removeAlert(item.id)} className="text-slate-500 hover:text-red-500">
                    <Trash2 size={18} />
                  </Button>
                </Card>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title={t.newAlert[language]}>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-2 text-sm font-medium">
              <span>{t.asset[language]}</span>
              <select value={asset} onChange={(event) => setAsset(event.target.value)} className="w-full rounded-lg border bg-white px-3 py-2 dark:border-white/10 dark:bg-[#1A1A1A]">
                {Object.entries(labels).map(([id, label]) => <option key={id} value={id}>{label[language]}</option>)}
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium">
              <span>{t.currency[language]}</span>
              <select value={mode} onChange={(event) => setMode(event.target.value as CurrencyMode)} className="w-full rounded-lg border bg-white px-3 py-2 dark:border-white/10 dark:bg-[#1A1A1A]">
                <option value="usd">USD</option><option value="toman">Toman</option>
              </select>
            </label>
          </div>
          <label className="block space-y-2 text-sm font-medium">
            <span>{t.target[language]}</span>
            <Input type="number" value={target} onChange={(event) => setTarget(event.target.value)} dir="ltr" />
          </label>
          <select value={condition} onChange={(event) => setCondition(event.target.value as 'above' | 'below')} className="w-full rounded-lg border bg-white px-3 py-2 dark:border-white/10 dark:bg-[#1A1A1A]">
            <option value="above">{t.above[language]}</option><option value="below">{t.below[language]}</option>
          </select>
          <div className={`space-y-3 rounded-xl border p-4 ${isDark ? 'border-white/10' : 'border-black/10'}`}>
            <div className="flex items-center justify-between"><span>{t.app[language]}</span><Switch checked={notifyApp} onCheckedChange={setNotifyApp} /></div>
            <div className="flex items-center justify-between"><span>{t.email[language]}</span><Switch checked={notifyEmail} onCheckedChange={setNotifyEmail} /></div>
          </div>
          <div className="flex gap-3 pt-2">
            <Button variant="primary" className="flex-1" disabled={isSaving || !target} onClick={() => void createAlert()}>
              {isSaving ? <Loader2 size={16} className="animate-spin" /> : t.create[language]}
            </Button>
            <Button variant="ghost" className="flex-1" onClick={() => setIsModalOpen(false)}>{t.cancel[language]}</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
