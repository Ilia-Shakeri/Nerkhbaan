import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { BellRing, BellOff, Trash2, Pencil, Search, Plus, ArrowUpRight, ArrowDownRight, Loader2 } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Switch } from '@nerkhbaan/ui/app/components/ui/switch';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { useAppContext } from '../context/AppContext';
import { api, type AlertResponse, type CurrencyMode, type NotificationPreferences, type PriceSourceMode } from '../services/api';
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
  const [loadError, setLoadError] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  // Null while creating; an id while editing an existing alert.
  const [editingId, setEditingId] = useState<number | null>(null);

  const [formAsset, setFormAsset] = useState('gold');
  const [formCondition, setFormCondition] = useState<'above' | 'below'>('above');
  const [formTargetPrice, setFormTargetPrice] = useState('');
  const [formCurrencyMode, setFormCurrencyMode] = useState<CurrencyMode>(currencyMode);
  const [formPriceSourceMode, setFormPriceSourceMode] = useState<PriceSourceMode | ''>('ordinary');
  const [editingSourceMode, setEditingSourceMode] = useState<string | null>(null);
  const [formNotifyApp, setFormNotifyApp] = useState(true);
  const [formNotifyEmail, setFormNotifyEmail] = useState(false);
  const [formNotifySms, setFormNotifySms] = useState(false);
  const [formNotifyVoip, setFormNotifyVoip] = useState(false);
  const [formPriority, setFormPriority] = useState<'normal' | 'critical'>('normal');
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const [preferencesError, setPreferencesError] = useState(false);
  const [preferencesRefresh, setPreferencesRefresh] = useState(0);
  const saving = useRef(false);

  const t = {
    search:     { fa: 'جستجوی هشدار...',        en: 'Search alerts...'   },
    newAlert:   { fa: 'هشدار جدید',             en: 'New Alert'          },
    asset:      { fa: 'دارایی',                 en: 'Asset'              },
    condition:  { fa: 'شرط',                    en: 'Condition'          },
    target:     { fa: 'قیمت هدف',               en: 'Target'             },
    currency:   { fa: 'واحد',                   en: 'Currency'           },
    priceUsed:  { fa: 'مبنای قیمت',             en: 'Price used'         },
    marketPrice:{ fa: 'قیمت بازار',             en: 'Market price'       },
    referencePrice:{ fa: 'نرخ مرجع منتشرشده',    en: 'Published reference' },
    derivedPrice:{ fa: 'قیمت محاسبه‌شده',        en: 'Calculated price'   },
    savedPrice: { fa: 'مبنای ذخیره‌شده حفظ شود', en: 'Keep saved price type' },
    status:     { fa: 'وضعیت',                  en: 'Status'             },
    above:      { fa: 'بیشتر از',               en: 'Above'              },
    below:      { fa: 'کمتر از',                en: 'Below'              },
    active:     { fa: 'فعال',                   en: 'Active'             },
    inactive:   { fa: 'غیرفعال',                en: 'Inactive'           },
    noAlerts:   { fa: 'هیچ هشداری ثبت نشده',    en: 'No alerts yet'      },
    createFirst:{ fa: 'اولین هشدار خود را ایجاد کنید', en: 'Create your first price alert' },
    deleteOk:   { fa: 'هشدار حذف شد',           en: 'Alert removed'      },
    deleteAlert:{ fa: 'حذف هشدار',              en: 'Delete alert'       },
    deleteConfirm:{ fa: 'این هشدار حذف شود؟',   en: 'Delete this alert?' },
    deleteFail: { fa: 'خطا در حذف هشدار',        en: 'Failed to remove'   },
    loadFail:   { fa: 'هشدارها بارگذاری نشدند', en: 'Alerts could not be loaded' },
    retry:      { fa: 'تلاش دوباره',             en: 'Try again'          },
    createOk:   { fa: 'هشدار ایجاد شد',         en: 'Alert created'      },
    createFail: { fa: 'خطا در ایجاد هشدار',      en: 'Failed to create'   },
    updateOk:   { fa: 'هشدار به‌روزرسانی شد',    en: 'Alert updated'      },
    updateFail: { fa: 'خطا در به‌روزرسانی',       en: 'Failed to update'   },
    editAlert:  { fa: 'ویرایش هشدار',           en: 'Edit Alert'         },
    save:       { fa: 'ذخیره',                  en: 'Save'               },
    notifyApp:  { fa: 'اعلان درون‌برنامه',       en: 'In-App Notification'},
    notifyEmail:{ fa: 'ایمیل',                  en: 'Email'              },
    notifySms:  { fa: 'پیامک',                  en: 'SMS'                },
    notifyVoip: { fa: 'تماس تلفنی',             en: 'Phone call'         },
    priority:   { fa: 'شدت هشدار',              en: 'Alert severity'     },
    normal:     { fa: 'عادی',                   en: 'Normal'             },
    critical:   { fa: 'بحرانی',                 en: 'Critical'           },
    create:     { fa: 'ایجاد',                  en: 'Create'             },
    cancel:     { fa: 'انصراف',                 en: 'Cancel'             },
  };

  const loadAlerts = async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const data = await api.alerts.list();
      setAlerts(data);
    } catch {
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { loadAlerts(); }, []);

  useEffect(() => {
    if (!isModalOpen) return;
    const controller = new AbortController();
    let active = true;
    setPreferencesLoading(true);
    setPreferencesError(false);
    setPreferences(null);
    api.notifications.preferences(controller.signal).then((value) => {
      if (active) setPreferences(value);
    }).catch(() => {
      if (active) setPreferencesError(true);
    }).finally(() => {
      if (active) setPreferencesLoading(false);
    });
    return () => { active = false; controller.abort(); };
  }, [isModalOpen, preferencesRefresh]);

  const phoneReady = Boolean(preferences?.sms_enabled && preferences.sms_verified && preferences.sms_phone);
  const smsReady = phoneReady && preferences?.sms_available === true;
  const voipReady = phoneReady && preferences?.voip_available === true
    && (preferences.voip_critical_only !== true || formPriority === 'critical');
  const paidChannelsBlocked = (formNotifySms && !smsReady) || (formNotifyVoip && !voipReady);
  const channelHelp = (channel: 'sms' | 'voip') => {
    if (preferencesLoading) return language === 'fa' ? 'در حال بررسی شماره و آمادگی سرویس…' : 'Checking the alert number and service…';
    if (preferencesError || !preferences) return language === 'fa' ? 'وضعیت سرویس دریافت نشد؛ پیش از فعال‌سازی دوباره بررسی کنید.' : 'Service status is unavailable. Check again before enabling.';
    if (!phoneReady) return language === 'fa' ? 'شمارهٔ هشدار باید در تنظیمات تأیید و فعال شود.' : 'Verify and enable your alert number in Settings.';
    if (channel === 'sms' && !preferences.sms_available) return language === 'fa' ? 'سرویس پیامک اکنون آماده نیست.' : 'SMS service is currently unavailable.';
    if (channel === 'voip' && !preferences.voip_available) return language === 'fa' ? 'سرویس یا قانون تماس اکنون آماده نیست.' : 'The calling service or policy is currently unavailable.';
    if (channel === 'voip' && preferences.voip_critical_only && formPriority !== 'critical') return language === 'fa' ? 'طبق قانون فعلی، تماس فقط برای هشدار بحرانی مجاز است.' : 'The current policy allows calls for critical alerts only.';
    return channel === 'sms'
      ? language === 'fa' ? 'در صورت برقرارشدن شرط، پیامک به شمارهٔ تأییدشده می‌رود.' : 'When the condition is met, SMS goes to your verified number.'
      : language === 'fa' ? 'تماس پس از پایداری شرط و با رعایت ساعت سکوت، فاصله و سقف تماس انجام می‌شود.' : 'Calls also follow condition persistence, quiet hours, cooldown and daily limits.';
  };

  const closeModal = () => {
    if (saving.current) return;
    setIsModalOpen(false);
    setEditingId(null);
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm(t.deleteConfirm[language])) return;
    try {
      await api.alerts.remove(id);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
      toast.success(t.deleteOk[language]);
    } catch {
      toast.error(t.deleteFail[language]);
    }
  };

  const openCreate = () => {
    setEditingId(null);
    setFormAsset('gold');
    setFormCondition('above');
    setFormTargetPrice('');
    setFormCurrencyMode(currencyMode);
    setFormPriceSourceMode('ordinary');
    setEditingSourceMode(null);
    setFormNotifyApp(true);
    setFormNotifyEmail(false);
    setFormNotifySms(false);
    setFormNotifyVoip(false);
    setFormPriority('normal');
    setPreferences(null);
    setPreferencesLoading(true);
    setPreferencesError(false);
    setIsModalOpen(true);
  };

  const openEdit = (alert: AlertResponse) => {
    setEditingId(alert.id);
    setFormAsset(alert.asset);
    setFormCondition(alert.condition);
    setFormTargetPrice(alert.target_price != null ? String(alert.target_price) : '');
    setFormCurrencyMode(alert.currency_mode);
    setEditingSourceMode(alert.price_source_mode ?? '');
    setFormPriceSourceMode(['ordinary', 'reference', 'derived'].includes(alert.price_source_mode)
      ? alert.price_source_mode : '');
    setFormNotifyApp(alert.notify_app);
    setFormNotifyEmail(alert.notify_email);
    setFormNotifySms(alert.notify_sms === true);
    setFormNotifyVoip(alert.notify_voip === true);
    setFormPriority(alert.priority === 'critical' ? 'critical' : 'normal');
    setPreferences(null);
    setPreferencesLoading(true);
    setPreferencesError(false);
    setIsModalOpen(true);
  };

  const handleSave = async () => {
    if (saving.current) return;
    const target = Number(formTargetPrice);
    if (!Number.isFinite(target) || target <= 0) { toast.error(language === 'fa' ? 'قیمت باید عدد مثبت باشد.' : 'Price must be a positive number.'); return; }
    if (paidChannelsBlocked) {
      toast.error(language === 'fa' ? 'برای پیامک یا تماس، شمارهٔ هشدار باید تأیید و فعال و سرویس آماده باشد. شرایط تماس بحرانی را هم بررسی کنید.' : 'SMS and calls require an active verified alert number and an available service. Check the critical-call policy too.');
      return;
    }
    saving.current = true;
    setIsSaving(true);
    try {
      if (editingId !== null) {
        // Editing in place keeps the alert's cooldown and trigger history,
        // which deleting and recreating threw away.
        const updated = await api.alerts.update(editingId, {
          asset: formAsset,
          target_price: parseFloat(formTargetPrice),
          currency_mode: formCurrencyMode,
          ...(formPriceSourceMode ? { price_source_mode: formPriceSourceMode } : {}),
          condition: formCondition,
          notify_app: formNotifyApp,
          notify_email: formNotifyEmail,
          notify_sms: formNotifySms,
          notify_voip: formNotifyVoip,
          priority: formPriority,
        });
        setAlerts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
        toast.success(t.updateOk[language]);
      } else {
        const created = await api.alerts.create({
          asset: formAsset,
          target_price: parseFloat(formTargetPrice),
          currency_mode: formCurrencyMode,
          price_source_mode: formPriceSourceMode || 'ordinary',
          condition: formCondition,
          notify_app: formNotifyApp,
          notify_email: formNotifyEmail,
          notify_sms: formNotifySms,
          notify_voip: formNotifyVoip,
          priority: formPriority,
          notify_webhook: false,
          webhook_url: null,
          enable_dlq: false,
        });
        setAlerts((prev) => [created, ...prev]);
        toast.success(t.createOk[language]);
      }
      setIsModalOpen(false);
      setFormTargetPrice('');
      setEditingId(null);
    } catch (error) {
      const fallback = editingId !== null ? t.updateFail[language] : t.createFail[language];
      toast.error(error instanceof Error ? error.message : fallback);
    } finally {
      saving.current = false;
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
            name="alert-search"
            type="search"
            aria-label={t.search[language]}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t.search[language]}
            className={`ps-9 rounded-xl ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA] placeholder:text-[#5A4E35]' : 'border-black/10 bg-white text-[#3B2E13] placeholder:text-[#A8883A]'}`}
          />
        </div>
        <Button
          onClick={openCreate}
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
      ) : loadError ? (
        <div className={`flex min-h-48 flex-col items-center justify-center gap-3 rounded-2xl border p-6 text-center ${isDark ? 'border-amber-500/20 bg-amber-500/5' : 'border-amber-500/30 bg-amber-50'}`} role="alert">
          <p className={isDark ? 'text-amber-200' : 'text-amber-800'}>{t.loadFail[language]}</p>
          <Button type="button" variant="outline" onClick={() => void loadAlerts()}>{t.retry[language]}</Button>
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
                  transition={{ type: 'spring', bounce: 0, duration: 0.28 }}
                  layout
                >
                  <Card className={`flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 rounded-2xl border p-4 backdrop-blur-md transition-[opacity,background-color,border-color] ${cardBase} ${!alert.is_active ? 'opacity-50' : ''}`}>
                    <div className="flex flex-1 items-center gap-4">
                      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${alert.is_active ? isDark ? 'bg-[#D4AF37]/10 text-[#D4AF37]' : 'bg-[#D4AF37]/15 text-[#8A6A20]' : isDark ? 'bg-white/5 text-[#4A3913]' : 'bg-black/5 text-[#C0A050]'}`}>
                        {alert.is_active ? <BellRing size={20} /> : <BellOff size={20} />}
                      </div>

                      <div className="flex flex-1 flex-wrap items-center gap-x-6 gap-y-2">
                        <div>
                          <div className={`text-xs font-medium uppercase tracking-wider ${isDark ? 'text-[#8A7A54]' : 'text-[#765C1F]'}`}>{t.asset[language]}</div>
                          <div className={`text-base font-bold ${isDark ? 'text-[#E2D3AA]' : 'text-[#3B2E13]'}`}>{assetLabel}</div>
                          {(alert.notify_sms || alert.notify_voip || alert.priority === 'critical') && <div className={`mt-1 flex flex-wrap gap-1.5 text-[11px] ${isDark ? 'text-[#C6B686]' : 'text-[#765C1F]'}`}>
                            {alert.notify_sms && <span>{t.notifySms[language]}</span>}
                            {alert.notify_voip && <span>{t.notifyVoip[language]}</span>}
                            {alert.priority === 'critical' && <span className="font-semibold">{t.critical[language]}</span>}
                          </div>}
                        </div>

                        <div className={`hidden sm:block h-8 w-px ${isDark ? 'bg-white/5' : 'bg-black/5'}`} />

                        <div>
                          <div className={`text-xs font-medium uppercase tracking-wider ${isDark ? 'text-[#8A7A54]' : 'text-[#765C1F]'}`}>{t.condition[language]}</div>
                          <div className={`mt-0.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${condColor}`} dir="ltr">
                            {alert.condition === 'above' ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                            {t[alert.condition][language]}
                          </div>
                        </div>

                        <div className={`hidden sm:block h-8 w-px ${isDark ? 'bg-white/5' : 'bg-black/5'}`} />

                        <div dir="ltr">
                          <div className={`text-xs font-medium uppercase tracking-wider ${isDark ? 'text-[#8A7A54]' : 'text-[#765C1F]'}`} dir={language === 'fa' ? 'rtl' : 'ltr'}>{t.target[language]}</div>
                          <div className={`font-bold tracking-wider ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                            {alert.alert_type === 'formula'
                              ? alert.formula
                              : `${alert.currency_mode === 'usd' ? '$' : ''}${alert.target_price?.toLocaleString() ?? '--'}${alert.currency_mode === 'toman' ? ' T' : ''}`}
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
                          aria-label={t.editAlert[language]}
                          onClick={() => openEdit(alert)}
                          className={`h-11 w-11 rounded-xl ${isDark ? 'text-[#8A7A54] hover:bg-[#D4AF37]/10 hover:text-[#D4AF37]' : 'text-[#8A6A25] hover:bg-[#D4AF37]/15 hover:text-[#6E5317]'}`}
                        >
                          <Pencil size={16} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={t.deleteAlert[language]}
                          onClick={() => handleDelete(alert.id)}
                          className={`h-11 w-11 rounded-xl ${isDark ? 'text-[#8A7A54] hover:bg-red-500/10 hover:text-red-400' : 'text-[#8A6A25] hover:bg-red-50 hover:text-red-600'}`}
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

      <Modal
        isOpen={isModalOpen}
        onClose={closeModal}
        title={editingId !== null ? t.editAlert[language] : t.newAlert[language]}
        closeLabel={language === 'fa' ? 'بستن پنجره هشدار' : 'Close alert dialog'}
      >
        <form className="space-y-5 pt-2" onSubmit={(event) => { event.preventDefault(); void handleSave(); }}>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label htmlFor="alert-asset" className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.asset[language]}</label>
              <select
                id="alert-asset"
                disabled={isSaving}
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
              <label htmlFor="alert-condition" className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.condition[language]}</label>
              <select
                id="alert-condition"
                disabled={isSaving}
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
              <label htmlFor="alert-target" className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.target[language]}</label>
              <Input
                id="alert-target"
                disabled={isSaving}
                min="0.00000001"
                step="any"
                type="number"
                dir="ltr"
                value={formTargetPrice}
                onChange={(e) => setFormTargetPrice(e.target.value)}
                placeholder="0.00"
                className={`rounded-xl ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="alert-currency" className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.currency[language]}</label>
              <select
                id="alert-currency"
                disabled={isSaving}
                value={formCurrencyMode}
                onChange={(e) => setFormCurrencyMode(e.target.value as CurrencyMode)}
                className={`w-full rounded-xl border px-3 py-2.5 text-sm font-medium ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}
              >
                <option value="usd">USD</option>
                <option value="toman">{language === 'fa' ? 'تومان' : 'Toman'}</option>
              </select>
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="alert-price-source" className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{t.priceUsed[language]}</label>
            <select
              id="alert-price-source"
              disabled={isSaving}
              value={formPriceSourceMode}
              onChange={(e) => setFormPriceSourceMode(e.target.value as PriceSourceMode)}
              aria-describedby="alert-price-source-help"
              className={`w-full rounded-xl border px-3 py-2.5 text-sm font-medium ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}
            >
              {formPriceSourceMode === '' && <option value="" disabled>{t.savedPrice[language]}</option>}
              <option value="ordinary">{t.marketPrice[language]}</option>
              <option value="reference">{t.referencePrice[language]}</option>
              {editingSourceMode === 'derived' && <option value="derived">{t.derivedPrice[language]}</option>}
            </select>
            <p id="alert-price-source-help" className={`text-xs ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>
              {formPriceSourceMode === 'reference'
                ? language === 'fa' ? 'هشدار با نرخ مرجعِ تازه سنجیده می‌شود؛ این نرخ ممکن است با قیمت معامله فرق داشته باشد.' : 'Uses fresh published reference rates, which may differ from trading prices.'
                : formPriceSourceMode === 'ordinary'
                  ? language === 'fa' ? 'هشدار با قیمت تازهٔ بازار سنجیده می‌شود؛ نرخ مرجع برای این گزینه به کار نمی‌رود.' : 'Uses fresh market prices. Published reference rates do not trigger this option.'
                  : language === 'fa' ? 'مبنای قیمتِ همین هشدار حفظ می‌شود.' : 'Keeps this alert’s saved price type.'}
            </p>
          </div>

          <div className={`space-y-3 rounded-xl border p-4 ${isDark ? 'border-white/5 bg-[#0A0A0A]' : 'border-black/5 bg-slate-50'}`}>
            <div className="flex items-center justify-between">
              <span className={`text-sm font-medium ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>{t.notifyApp[language]}</span>
              <Switch checked={formNotifyApp} onCheckedChange={setFormNotifyApp} disabled={isSaving} aria-label={t.notifyApp[language]} />
            </div>
            <div className="flex items-center justify-between">
              <span className={`text-sm font-medium ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>{t.notifyEmail[language]}</span>
              <Switch checked={formNotifyEmail} onCheckedChange={setFormNotifyEmail} disabled={isSaving} aria-label={t.notifyEmail[language]} />
            </div>
          </div>

          <section aria-labelledby="alert-paid-channels" className={`space-y-4 rounded-xl border p-4 ${isDark ? 'border-[#D4AF37]/15 bg-[#D4AF37]/5' : 'border-[#D4AF37]/25 bg-amber-50/50'}`}>
            <div>
              <h3 id="alert-paid-channels" className={`text-sm font-semibold ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{language === 'fa' ? 'پیامک و تماس برای این هشدار' : 'SMS and calls for this alert'}</h3>
              <p className={`mt-1 text-xs leading-6 ${isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>{language === 'fa' ? 'فعال‌سازی اختیاری است. ذخیرهٔ فرم، پیامک یا تماس آزمون ایجاد نمی‌کند.' : 'Optional. Saving this form does not send a test SMS or call.'}</p>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="alert-priority" className={`text-sm font-medium ${isDark ? 'text-[#C6B686]' : 'text-[#7A5E24]'}`}>{t.priority[language]}</label>
              <select id="alert-priority" value={formPriority} disabled={isSaving} onChange={(event) => setFormPriority(event.target.value as 'normal' | 'critical')}
                className={`w-full rounded-xl border px-3 py-2.5 text-sm ${isDark ? 'border-white/10 bg-[#111111] text-[#E2D3AA]' : 'border-black/10 bg-white text-[#3B2E13]'}`}>
                <option value="normal">{t.normal[language]}</option><option value="critical">{t.critical[language]}</option>
              </select>
            </div>
            {(['sms', 'voip'] as const).map((channel) => {
              const enabled = channel === 'sms' ? formNotifySms : formNotifyVoip;
              const ready = channel === 'sms' ? smsReady : voipReady;
              const label = channel === 'sms' ? t.notifySms[language] : t.notifyVoip[language];
              return <div key={channel} className="space-y-1">
                <div className="flex items-center justify-between gap-3">
                  <label htmlFor={`alert-notify-${channel}`} className={`text-sm font-medium ${isDark ? 'text-[#C6B686]' : 'text-[#7A5E24]'}`}>{label}</label>
                  <Switch id={`alert-notify-${channel}`} checked={enabled} onCheckedChange={channel === 'sms' ? setFormNotifySms : setFormNotifyVoip}
                    disabled={isSaving || (!ready && !enabled)} aria-label={label} aria-describedby={`alert-${channel}-help`} />
                </div>
                <p id={`alert-${channel}-help`} className={`text-xs leading-6 ${enabled && !ready ? isDark ? 'text-amber-200' : 'text-amber-900' : isDark ? 'text-[#A89668]' : 'text-[#7A5E24]'}`}>{channelHelp(channel)}</p>
              </div>;
            })}
            {paidChannelsBlocked && <p role="alert" className={`text-xs leading-6 ${isDark ? 'text-amber-200' : 'text-amber-900'}`}>{language === 'fa' ? 'انتخاب ذخیره‌شده حفظ شده است. برای ذخیره، پیش‌نیاز را فراهم کنید یا کانال انتخابی را خاموش کنید.' : 'Your saved choice is preserved. Restore its prerequisites or turn the selected channel off before saving.'}</p>}
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <Link to="/settings" onClick={(event) => { if (saving.current) { event.preventDefault(); return; } closeModal(); }} className={`rounded-md underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D4AF37] ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{language === 'fa' ? 'تأیید و فعال‌سازی شماره در تنظیمات' : 'Verify and enable your number in Settings'}</Link>
              {preferencesError && <button type="button" disabled={isSaving || preferencesLoading} onClick={() => setPreferencesRefresh((value) => value + 1)} className={`min-h-11 rounded-md px-2 underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-[#D4AF37] ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>{language === 'fa' ? 'بررسی دوبارهٔ سرویس' : 'Check service again'}</button>}
            </div>
          </section>

          <div className="flex gap-3">
            <Button
              type="button"
              variant="outline"
              className={`flex-1 rounded-xl ${isDark ? 'border-white/10 text-[#A89668]' : 'border-black/10 text-[#8A6A25]'}`}
              onClick={closeModal}
              disabled={isSaving}
            >
              {t.cancel[language]}
            </Button>
            <Button
              type="submit"
              disabled={isSaving || !formTargetPrice || paidChannelsBlocked}
              className="flex-1 rounded-xl bg-[#D4AF37] font-semibold text-black hover:bg-[#E8C45A] disabled:opacity-50"
            >
              {isSaving
                ? <Loader2 size={16} className="animate-spin" />
                : editingId !== null ? t.save[language] : t.create[language]}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
