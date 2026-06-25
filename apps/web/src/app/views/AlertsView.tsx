import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { BellRing, BellOff, Trash2, Search, Plus, ArrowUpRight, ArrowDownRight, Loader2 } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { useAppContext } from '../context/AppContext';
import { api, type AlertResponse, type CurrencyMode } from '../services/api';
import { toast } from 'sonner';

const ASSET_LABELS: Record<string, { fa: string; en: string }> = {
  gold:   { fa: 'طلا',       en: 'Gold'    },
  silver: { fa: 'نقره',      en: 'Silver'  },
  usdt:   { fa: 'تتر',       en: 'Tether'  },
  btc:    { fa: 'بیت‌کوین',  en: 'Bitcoin' },
};

export function AlertsView() {
  const { language, theme, currencyMode } = useAppContext();
  const isDark = theme === 'dark';

  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const [formAsset, setFormAsset] = useState('gold');
  const [formCondition, setFormCondition] = useState<'above' | 'below'>('above');
  const [formTargetPrice, setFormTargetPrice] = useState('');
  const [formCurrencyMode, setFormCurrencyMode] = useState<CurrencyMode>(currencyMode);
  const [formNotifyApp, setFormNotifyApp] = useState(true);
  const [formNotifyEmail, setFormNotifyEmail] = useState(false);

  const t = {
    search:     { fa: 'جستجوی هشدار...',        en: 'Search alerts...'   },
    newAlert:   { fa: 'هشدار جدید',             en: 'New Alert'          },
    asset:      { fa: 'دارایی',                 en: 'Asset'              },
    condition:  { fa: 'شرط',                    en: 'Condition'          },
    target:     { fa: 'قیمت هدف',               en: 'Target'             },
    currency:   { fa: 'واحد',                   en: 'Currency'           },
    status:     { fa: 'وضعیت',                  en: 'Status'             },
    above:      { fa: 'بیشتر از',               en: 'Above'              },
    below:      { fa: 'کمتر از',                en: 'Below'              },
    active:     { fa: 'فعال',                   en: 'Active'             },
    inactive:   { fa: 'غیرفعال',                en: 'Inactive'           },
    noAlerts:   { fa: 'هیچ هشداری ثبت نشده',    en: 'No alerts yet'      },
    createFirst:{ fa: 'اولین هشدار خود را ایجاد کنید', en: 'Create your first price alert' },
    deleteOk:   { fa: 'هشدار حذف شد',           en: 'Alert removed'      },
    deleteFail: { fa: 'خطا در حذف هشدار',        en: 'Failed to remove'   },
    createOk:   { fa: 'هشدار ایجاد شد',         en: 'Alert created'      },
    createFail: { fa: 'خطا در ایجاد هشدار',      en: 'Failed to create'   },
    notifyApp:  { fa: 'اعلان درون‌برنامه',       en: 'In-App Notification'},
    notifyEmail:{ fa: 'ایمیل',                  en: 'Email'              },
    create:     { fa: 'ایجاد',                  en: 'Create'             },
    cancel:     { fa: 'انصراف',                 en: 'Cancel'             },
  };

  const loadAlerts = async () => {
    try {
      const data = await api.alerts.list();
      setAlerts(data);
    } catch {
      // Silently fail — the list stays empty and user can retry via new alert creation
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { loadAlerts(); }, []);

  const handleDelete = async (id: number) => {
    try {
      await api.alerts.remove(id);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
      toast.success(t.deleteOk[language]);
    } catch {
      toast.error(t.deleteFail[language]);
    }
  };

  const handleCreate = async () => {
    if (!formTargetPrice) return;
    setIsSaving(true);
    try {
      const created = await api.alerts.create({
        asset: formAsset,
        target_price: parseFloat(formTargetPrice),
        currency_mode: formCurrencyMode,
        condition: formCondition,
        notify_app: formNotifyApp,
        notify_email: formNotifyEmail,
        notify_webhook: false,
        webhook_url: null,
        enable_dlq: false,
      });
      setAlerts((prev) => [created, ...prev]);
      toast.success(t.createOk[language]);
      setIsModalOpen(false);
      setFormTargetPrice('');
    } catch {
      toast.error(t.createFail[language]);
    } finally {
      setIsSaving(false);
    }
  };

  const filtered = alerts.filter((a) => {
    const label = ASSET_LABELS[a.asset]?.[language] ?? a.asset;
    return label.toLowerCase().includes(searchQuery.toLowerCase());
  });

  const cardBase = isDark
    ? 'border-white/5 bg-[#0E0E0E]/70'
    : 'border-black/5 bg-white/70';

  return (
    <div className="mx-auto max-w-4xl space-y-6">

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className={`absolute start-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-[#9C8A5D]' : 'text-[#A8883A]'}`} size={16} />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t.search[language]}
            className={`ps-9 rounded-xl ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA] placeholder:text-[#5A4E35]' : 'border-black/10 bg-white text-[#3B2E13] placeholder:text-[#A8883A]'}`}
          />
        </div>
        <Button
          onClick={() => setIsModalOpen(true)}
          className={`shrink-0 gap-2 rounded-xl font-semibold ${isDark ? 'bg-[#D4AF37] text-black hover:bg-[#E8C45A]' : 'bg-[#D4AF37] text-black hover:bg-[#C49A20]'}`}
        >
          <Plus size={16} />
          {t.newAlert[language]}
        </Button>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 size={28} className={`animate-spin ${isDark ? 'text-[#D4AF37]' : 'text-[#9D7A20]'}`} />
        </div>
      ) : filtered.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className={`flex flex-col items-center justify-center gap-3 rounded-[2rem] border py-20 text-center ${isDark ? 'border-white/5 bg-[#0E0E0E]/40' : 'border-black/5 bg-white/40'}`}
        >
          <BellOff size={40} className={isDark ? 'text-[#4A3913]' : 'text-[#D4AF37]'} />
          <p className={`font-semibold ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>{t.noAlerts[language]}</p>
          <p className={`text-sm ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.createFirst[language]}</p>
        </motion.div>
      ) : (
        <div className="grid gap-3">
          <AnimatePresence>
            {filtered.map((alert) => {
              const assetLabel = ASSET_LABELS[alert.asset]?.[language] ?? alert.asset;
              const condColor = alert.condition === 'above'
                ? isDark ? 'bg-emerald-500/10 text-emerald-400' : 'bg-emerald-100 text-emerald-700'
                : isDark ? 'bg-red-500/10 text-red-400' : 'bg-red-100 text-red-700';

              return (
                <motion.div
                  key={alert.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.97 }}
                  layout
                >
                  <Card className={`flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 rounded-2xl border p-4 backdrop-blur-md transition-all ${cardBase} ${!alert.is_active ? 'opacity-50' : ''}`}>
                    <div className="flex flex-1 items-center gap-4">
                      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${alert.is_active ? isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37]' : 'bg-[#D4AF37]/15 text-[#8A6A20]' : isDark ? 'bg-white/5 text-[#4A3913]' : 'bg-black/5 text-[#C0A050]'}`}>
                        {alert.is_active ? <BellRing size={20} /> : <BellOff size={20} />}
                      </div>

                      <div className="flex flex-1 flex-wrap items-center gap-x-6 gap-y-2">
                        <div>
                          <div className={`text-[10px] font-medium uppercase tracking-wider ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.asset[language]}</div>
                          <div className={`text-base font-bold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{assetLabel}</div>
                        </div>

                        <div className={`hidden sm:block h-8 w-px ${isDark ? 'bg-white/5' : 'bg-black/5'}`} />

                        <div>
                          <div className={`text-[10px] font-medium uppercase tracking-wider ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`}>{t.condition[language]}</div>
                          <div className={`mt-0.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${condColor}`} dir="ltr">
                            {alert.condition === 'above' ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                            {t[alert.condition][language]}
                          </div>
                        </div>

                        <div className={`hidden sm:block h-8 w-px ${isDark ? 'bg-white/5' : 'bg-black/5'}`} />

                        <div dir="ltr">
                          <div className={`text-[10px] font-medium uppercase tracking-wider ${isDark ? 'text-[#5A4E35]' : 'text-[#A8883A]'}`} dir={language === 'fa' ? 'rtl' : 'ltr'}>{t.target[language]}</div>
                          <div className={`font-bold tracking-wider ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                            {alert.currency_mode === 'usd' ? '$' : ''}{alert.target_price.toLocaleString()}
                            {alert.currency_mode === 'toman' ? ' T' : ''}
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className={`flex w-full items-center justify-between border-t pt-3 sm:w-auto sm:border-t-0 sm:pt-0 ${isDark ? 'border-white/5' : 'border-black/5'}`}>
                      <div className="flex items-center gap-2">
                        <div className={`h-2 w-2 rounded-full ${alert.is_active ? 'bg-emerald-400' : isDark ? 'bg-white/20' : 'bg-black/20'}`} />
                        <span className={`text-xs font-medium ${isDark ? 'text-[#A89668]' : 'text-[#8A6A25]'}`}>
                          {alert.is_active ? t.active[language] : t.inactive[language]}
                        </span>
                      </div>

                      <div className={`flex items-center gap-1 border-s ps-4 ms-3 ${isDark ? 'border-white/5' : 'border-black/5'}`}>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(alert.id)}
                          className={`h-9 w-9 rounded-lg ${isDark ? 'text-[#5A4E35] hover:bg-red-500/10 hover:text-red-400' : 'text-[#C0A050] hover:bg-red-50 hover:text-red-600'}`}
                        >
                          <Trash2 size={16} />
                        </Button>
                      </div>
                    </div>
                  </Card>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}

      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title={t.newAlert[language]}>
        <div className="space-y-5 pt-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.asset[language]}</label>
              <select
                value={formAsset}
                onChange={(e) => setFormAsset(e.target.value)}
                className={`w-full rounded-xl border px-3 py-2.5 text-sm font-medium ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}
              >
                {Object.entries(ASSET_LABELS).map(([id, label]) => (
                  <option key={id} value={id}>{label[language]}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.condition[language]}</label>
              <select
                value={formCondition}
                onChange={(e) => setFormCondition(e.target.value as 'above' | 'below')}
                className={`w-full rounded-xl border px-3 py-2.5 text-sm font-medium ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}
              >
                <option value="above">{t.above[language]}</option>
                <option value="below">{t.below[language]}</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.target[language]}</label>
              <Input
                type="number"
                dir="ltr"
                value={formTargetPrice}
                onChange={(e) => setFormTargetPrice(e.target.value)}
                placeholder="0.00"
                className={`rounded-xl ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}
              />
            </div>
            <div className="space-y-1.5">
              <label className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.currency[language]}</label>
              <select
                value={formCurrencyMode}
                onChange={(e) => setFormCurrencyMode(e.target.value as CurrencyMode)}
                className={`w-full rounded-xl border px-3 py-2.5 text-sm font-medium ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}
              >
                <option value="usd">USD</option>
                <option value="toman">{language === 'fa' ? 'تومان' : 'Toman'}</option>
              </select>
            </div>
          </div>

          <div className={`space-y-3 rounded-xl border p-4 ${isDark ? 'border-white/5 bg-[#0A0A0A]' : 'border-black/5 bg-slate-50'}`}>
            <div className="flex items-center justify-between">
              <span className={`text-sm font-medium ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>{t.notifyApp[language]}</span>
              <Switch checked={formNotifyApp} onCheckedChange={setFormNotifyApp} />
            </div>
            <div className="flex items-center justify-between">
              <span className={`text-sm font-medium ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>{t.notifyEmail[language]}</span>
              <Switch checked={formNotifyEmail} onCheckedChange={setFormNotifyEmail} />
            </div>
          </div>

          <div className="flex gap-3">
            <Button
              variant="outline"
              className={`flex-1 rounded-xl ${isDark ? 'border-white/10 text-[#A89668]' : 'border-black/10 text-[#8A6A25]'}`}
              onClick={() => setIsModalOpen(false)}
            >
              {t.cancel[language]}
            </Button>
            <Button
              disabled={isSaving || !formTargetPrice}
              onClick={handleCreate}
              className="flex-1 rounded-xl bg-[#D4AF37] font-semibold text-black hover:bg-[#E8C45A] disabled:opacity-50"
            >
              {isSaving ? <Loader2 size={16} className="animate-spin" /> : t.create[language]}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
