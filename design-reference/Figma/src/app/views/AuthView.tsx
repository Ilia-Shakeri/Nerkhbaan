import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Activity, ArrowLeft } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { Input } from '../components/ui/Input';
import { Button } from '../components/ui/Button';

import { toast } from 'sonner';

export function AuthView() {
  const { login, language, theme, toggleTheme, toggleLanguage } = useAppContext();
  const [isLogin, setIsLogin] = useState(true);

  const t = {
    welcome: { fa: 'خوش آمدید', en: 'Welcome back' },
    createAccount: { fa: 'ایجاد حساب کاربری', en: 'Create an account' },
    subWelcome: { fa: 'برای ادامه وارد حساب خود شوید', en: 'Log in to your account to continue' },
    subCreate: { fa: 'برای استفاده از نرخ‌بان ثبت‌نام کنید', en: 'Sign up to start using Rateban' },
    phoneOrEmail: { fa: 'ایمیل یا شماره موبایل', en: 'Email or Phone Number' },
    password: { fa: 'رمز عبور', en: 'Password' },
    confirmPassword: { fa: 'تکرار رمز عبور', en: 'Confirm Password' },
    forgotPassword: { fa: 'رمز عبور را فراموش کرده‌اید؟', en: 'Forgot password?' },
    loginBtn: { fa: 'ورود به حساب', en: 'Sign In' },
    registerBtn: { fa: 'ثبت‌نام', en: 'Sign Up' },
    noAccount: { fa: 'حساب کاربری ندارید؟', en: "Don't have an account?" },
    haveAccount: { fa: 'قبلاً ثبت‌نام کرده‌اید؟', en: 'Already have an account?' },
    registerLink: { fa: 'ثبت‌نام کنید', en: 'Sign up here' },
    loginLink: { fa: 'وارد شوید', en: 'Log in here' },
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-[#F8FAFC] dark:bg-[#0A0A0A] p-4 font-[Vazirmatn]">
      
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-[20%] -end-[10%] h-[500px] w-[500px] rounded-full bg-[#D4AF37]/5 blur-[120px] dark:bg-[#D4AF37]/10" />
        <div className="absolute -bottom-[20%] -start-[10%] h-[500px] w-[500px] rounded-full bg-[#0B1F3A]/5 blur-[120px] dark:bg-[#10B981]/5" />
      </div>

      <div className="absolute top-6 end-6 flex items-center gap-3">
        <button onClick={toggleLanguage} className="text-sm font-medium text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors">
          {language === 'fa' ? 'English' : 'فارسی'}
        </button>
        <div className="h-4 w-[1px] bg-slate-200 dark:bg-white/10" />
        <button onClick={toggleTheme} className="text-sm font-medium text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors">
          {theme === 'dark' ? (language === 'fa' ? 'روز' : 'Light') : (language === 'fa' ? 'شب' : 'Dark')}
        </button>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-md rounded-[2rem] border border-slate-200/50 bg-white/70 p-8 shadow-2xl backdrop-blur-xl dark:border-white/10 dark:bg-[#121212]/80 sm:p-10"
      >
        <div className="mb-10 flex flex-col items-center text-center">
          <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#D4AF37] text-[#0A0A0A] shadow-[0_4px_20px_0_rgba(212,175,55,0.4)]">
            <Activity size={32} strokeWidth={2.5} />
          </div>
          <h1 className="mb-2 text-2xl font-bold tracking-tight text-[#0B1F3A] dark:text-white">
            {isLogin ? t.welcome[language] : t.createAccount[language]}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {isLogin ? t.subWelcome[language] : t.subCreate[language]}
          </p>
        </div>

        <form onSubmit={(e) => { 
          e.preventDefault(); 
          toast.success(language === 'fa' ? 'با موفقیت وارد شدید' : 'Logged in successfully');
          login(); 
        }} className="space-y-5">
          <div className="space-y-1 text-start">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300 px-1">
              {t.phoneOrEmail[language]}
            </label>
            <Input
              type="text"
              placeholder="name@example.com"
              className="h-12 rounded-xl text-start"
              dir="ltr"
            />
          </div>

          <div className="space-y-1 text-start">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300 px-1">
              {t.password[language]}
            </label>
            <Input
              type="password"
              placeholder="••••••••"
              className="h-12 rounded-xl text-start tracking-widest font-sans"
              dir="ltr"
            />
          </div>

          {!isLogin && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className="space-y-1 text-start"
            >
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300 px-1">
                {t.confirmPassword[language]}
              </label>
              <Input
                type="password"
                placeholder="••••••••"
                className="h-12 rounded-xl text-start tracking-widest font-sans"
                dir="ltr"
              />
            </motion.div>
          )}

          {isLogin && (
            <div className="flex justify-end">
              <button type="button" className="text-sm font-medium text-[#D4AF37] hover:text-[#C29D29] hover:underline underline-offset-4">
                {t.forgotPassword[language]}
              </button>
            </div>
          )}

          <Button type="submit" variant="primary" size="lg" className="w-full mt-2">
            {isLogin ? t.loginBtn[language] : t.registerBtn[language]}
          </Button>
        </form>

        <div className="mt-8 text-center text-sm text-slate-500 dark:text-slate-400">
          {isLogin ? t.noAccount[language] : t.haveAccount[language]}{' '}
          <button
            onClick={() => setIsLogin(!isLogin)}
            className="font-medium text-[#0B1F3A] hover:underline underline-offset-4 dark:text-white"
          >
            {isLogin ? t.registerLink[language] : t.loginLink[language]}
          </button>
        </div>
      </motion.div>
    </div>
  );
}
