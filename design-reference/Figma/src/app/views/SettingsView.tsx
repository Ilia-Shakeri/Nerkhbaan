import React from 'react';
import { motion } from 'motion/react';
import { Moon, Sun, Languages, Bell, Smartphone, Mail, Send, Activity, ShieldCheck, LifeBuoy } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Switch } from '../components/ui/Switch';
import { useAppContext } from '../context/AppContext';

export function SettingsView() {
  const { language, theme, toggleTheme, toggleLanguage } = useAppContext();

  const t = {
    general: { fa: 'عمومی', en: 'General' },
    notifications: { fa: 'اطلاع‌رسانی', en: 'Notifications' },
    behavior: { fa: 'رفتار برنامه', en: 'Behavior' },
    support: { fa: 'پشتیبانی', en: 'Support' },
    darkTheme: { fa: 'حالت تاریک', en: 'Dark Theme' },
    languageSet: { fa: 'زبان برنامه', en: 'App Language' },
    pushApp: { fa: 'اعلان درون‌برنامه‌ای (Push)', en: 'In-App Push' },
    sms: { fa: 'پیامک (SMS)', en: 'SMS Notifications' },
    email: { fa: 'ایمیل', en: 'Email Notifications' },
    telegram: { fa: 'ربات تلگرام', en: 'Telegram Bot' },
    aggressive: { fa: 'حالت هشدار مکرر', en: 'Aggressive Alerts' },
    silent: { fa: 'حالت بی‌صدا', en: 'Silent Mode' },
    contact: { fa: 'تماس با ما', en: 'Contact Us' },
    privacy: { fa: 'حریم خصوصی', en: 'Privacy Policy' },
  };

  return (
    <div className="mx-auto max-w-4xl space-y-8 pb-10">
      
      {/* General Settings */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <h2 className="mb-4 text-xl font-bold tracking-tight text-[#0B1F3A] dark:text-white flex items-center gap-2">
          <Activity className="text-[#D4AF37]" size={24} />
          {t.general[language]}
        </h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5">
          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-700 dark:bg-white/5 dark:text-slate-300">
                {theme === 'dark' ? <Moon size={20} /> : <Sun size={20} />}
              </div>
              <div className="flex flex-col">
                <span className="font-semibold text-slate-900 dark:text-white">{t.darkTheme[language]}</span>
                <span className="text-sm text-slate-500 dark:text-slate-400">تغییر ظاهر برنامه به حالت شب</span>
              </div>
            </div>
            <Switch checked={theme === 'dark'} onCheckedChange={toggleTheme} />
          </div>
          
          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-700 dark:bg-white/5 dark:text-slate-300">
                <Languages size={20} />
              </div>
              <div className="flex flex-col">
                <span className="font-semibold text-slate-900 dark:text-white">{t.languageSet[language]}</span>
                <span className="text-sm text-slate-500 dark:text-slate-400">فارسی / English</span>
              </div>
            </div>
            <button
              onClick={toggleLanguage}
              className="flex items-center gap-2 rounded-lg bg-slate-100 px-4 py-2 text-sm font-semibold transition-colors hover:bg-slate-200 dark:bg-white/10 dark:hover:bg-white/20"
            >
              {language === 'fa' ? 'English' : 'فارسی'}
            </button>
          </div>
        </Card>
      </motion.div>

      {/* Notification Channels */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
        <h2 className="mb-4 text-xl font-bold tracking-tight text-[#0B1F3A] dark:text-white flex items-center gap-2">
          <Bell className="text-[#D4AF37]" size={24} />
          {t.notifications[language]}
        </h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5">
          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400">
                <Bell size={20} />
              </div>
              <span className="font-semibold text-slate-900 dark:text-white">{t.pushApp[language]}</span>
            </div>
            <Switch checked={true} onCheckedChange={() => {}} />
          </div>
          
          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400">
                <Smartphone size={20} />
              </div>
              <span className="font-semibold text-slate-900 dark:text-white">{t.sms[language]}</span>
            </div>
            <Switch checked={false} onCheckedChange={() => {}} />
          </div>

          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-50 text-purple-600 dark:bg-purple-500/10 dark:text-purple-400">
                <Mail size={20} />
              </div>
              <span className="font-semibold text-slate-900 dark:text-white">{t.email[language]}</span>
            </div>
            <Switch checked={false} onCheckedChange={() => {}} />
          </div>

          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400">
                <Send size={20} />
              </div>
              <span className="font-semibold text-slate-900 dark:text-white">{t.telegram[language]}</span>
            </div>
            <Switch checked={true} onCheckedChange={() => {}} />
          </div>
        </Card>
      </motion.div>

      {/* Behavior */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
        <h2 className="mb-4 text-xl font-bold tracking-tight text-[#0B1F3A] dark:text-white flex items-center gap-2">
          <Activity className="text-[#D4AF37]" size={24} />
          {t.behavior[language]}
        </h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5">
          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex flex-col">
                <span className="font-semibold text-slate-900 dark:text-white">{t.silent[language]}</span>
                <span className="text-sm text-slate-500 dark:text-slate-400">عدم پخش صدا برای هشدارها</span>
              </div>
            </div>
            <Switch checked={false} onCheckedChange={() => {}} />
          </div>
          <div className="flex items-center justify-between p-5">
            <div className="flex items-center gap-4">
              <div className="flex flex-col">
                <span className="font-semibold text-slate-900 dark:text-white">{t.aggressive[language]}</span>
                <span className="text-sm text-slate-500 dark:text-slate-400">تکرار هشدار تا زمان مشاهده</span>
              </div>
            </div>
            <Switch checked={true} onCheckedChange={() => {}} />
          </div>
        </Card>
      </motion.div>

      {/* Support */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
        <h2 className="mb-4 text-xl font-bold tracking-tight text-[#0B1F3A] dark:text-white flex items-center gap-2">
          <LifeBuoy className="text-[#D4AF37]" size={24} />
          {t.support[language]}
        </h2>
        <Card className="divide-y divide-slate-100 dark:divide-white/5">
          <button className="flex w-full items-center gap-4 p-5 text-start transition-colors hover:bg-slate-50 dark:hover:bg-white/5">
             <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-700 dark:bg-white/5 dark:text-slate-300">
                <LifeBuoy size={20} />
             </div>
             <span className="font-semibold text-slate-900 dark:text-white">{t.contact[language]}</span>
          </button>
          <button className="flex w-full items-center gap-4 p-5 text-start transition-colors hover:bg-slate-50 dark:hover:bg-white/5">
             <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-700 dark:bg-white/5 dark:text-slate-300">
                <ShieldCheck size={20} />
             </div>
             <span className="font-semibold text-slate-900 dark:text-white">{t.privacy[language]}</span>
          </button>
        </Card>
      </motion.div>

    </div>
  );
}
