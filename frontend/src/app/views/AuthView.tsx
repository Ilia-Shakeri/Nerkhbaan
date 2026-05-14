// frontend/src/app/views/AuthView.tsx

import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Moon, Sun, User, Mail, Lock } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { toast } from 'sonner';
import mainLogo from '../../logo/main-logo.png';
import fallbackLogo from '../../logo/logo.png';

export function AuthView() {
  const navigate = useNavigate();
  const { login, language, theme, toggleTheme, toggleLanguage } = useAppContext();

  const [isLogin, setIsLogin] = useState(true);
  const [fullName, setFullName] = useState('');
  const [emailOrPhone, setEmailOrPhone] = useState('');
  const [password, setPassword] = useState('');

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Alerta' },
    brandTagline: { fa: 'ردیابی و هشدار هوشمند قیمت', en: 'Smart price tracking & alerts' },
    login: { fa: 'ورود', en: 'Login' },
    signup: { fa: 'ثبت نام', en: 'Sign Up' },
    fullName: { fa: 'نام کامل', en: 'Full Name' },
    email: { fa: 'ایمیل', en: 'Email' },
    password: { fa: 'رمز عبور', en: 'Password' },
    remember: { fa: 'مرا به خاطر بسپار', en: 'Remember me' },
    forgot: { fa: 'فراموشی؟', en: 'Forgot?' },
    signIn: { fa: 'ورود به حساب', en: 'Sign In' },
    createAccount: { fa: 'ایجاد حساب', en: 'Create Account' },
    terms: {
      fa: 'با ادامه، شما با شرایط استفاده و حریم خصوصی موافقید',
      en: 'By continuing, you agree to our Terms of Service and Privacy Policy'
    },
    themeToggle: { fa: 'تغییر حالت', en: 'Toggle theme' },
    languageToggle: { fa: 'English', en: 'فارسی' },
    fillFields: { fa: 'لطفا همه فیلدها را کامل کنید', en: 'Please fill in all fields' },
    success: { fa: 'با موفقیت وارد شدید', en: 'Logged in successfully' },
    failed: { fa: 'ورود ناموفق بود', en: 'Login failed' }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!emailOrPhone || !password || (!isLogin && !fullName)) {
      toast.error(t.fillFields[language]);
      return;
    }

    try {
      const token = 'demo-token-12345';
      login(token);
      toast.success(t.success[language]);
      navigate('/');
    } catch (error) {
      console.error(error);
      toast.error(t.failed[language]);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#060606] text-[#F7F2E3]">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(212,175,55,0.18),transparent_58%)]" />

      <div className="absolute end-6 top-6 z-20 flex items-center gap-3">
        <button
          type="button"
          aria-label={t.languageToggle[language]}
          onClick={toggleLanguage}
          className="rounded-full border border-[#D4AF37]/35 bg-[#121212] px-3 py-1.5 text-[#D9BE66] transition hover:bg-[#1A1A1A]"
        >
          <span className="text-xs font-semibold">{t.languageToggle[language]}</span>
        </button>
        <button
          type="button"
          aria-label={t.themeToggle[language]}
          onClick={toggleTheme}
          className="rounded-full border border-[#D4AF37]/35 bg-[#121212] p-2 text-[#D9BE66] transition hover:bg-[#1A1A1A]"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </div>

      <div className="relative z-10 mx-auto flex w-full max-w-5xl flex-col px-6 pb-10 pt-10">
        <div className="mb-8 flex flex-col items-center text-center">
          <img
            src={mainLogo}
            alt={t.brandName[language]}
            className="mb-2 h-[118px] w-[118px] object-contain md:h-[138px] md:w-[138px]"
            onError={(event) => {
              event.currentTarget.src = fallbackLogo;
            }}
          />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="mx-auto w-full max-w-xl rounded-3xl border border-[#D4AF37]/25 bg-[#111111]/96 p-5 shadow-[0_24px_60px_rgba(0,0,0,0.55)]"
        >
          <div className="mb-5 grid grid-cols-2 rounded-xl bg-[#171717] p-1">
            <button
              type="button"
              onClick={() => setIsLogin(true)}
              className={`h-10 rounded-lg text-sm font-semibold transition ${
                isLogin ? 'bg-[#D4AF37] text-[#0A0A0A]' : 'text-[#B9A46A]'
              }`}
            >
              {t.login[language]}
            </button>
            <button
              type="button"
              onClick={() => setIsLogin(false)}
              className={`h-10 rounded-lg text-sm font-semibold transition ${
                !isLogin ? 'bg-[#D4AF37] text-[#0A0A0A]' : 'text-[#B9A46A]'
              }`}
            >
              {t.signup[language]}
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-[#E9D49A]">{t.fullName[language]}</label>
                <div className="relative">
                  <User size={18} className="pointer-events-none absolute start-4 top-1/2 -translate-y-1/2 text-[#CDB879]/55" />
                  <Input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="John Doe"
                    dir="ltr"
                    className="h-11 rounded-xl border-[#D4AF37]/18 bg-[#1B1B1B] ps-11 text-sm text-[#F7F2E3] placeholder:text-[#CDB879]/35"
                  />
                </div>
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium text-[#E9D49A]">{t.email[language]}</label>
              <div className="relative">
                <Mail size={18} className="pointer-events-none absolute start-4 top-1/2 -translate-y-1/2 text-[#CDB879]/55" />
                <Input
                  type="text"
                  value={emailOrPhone}
                  onChange={(e) => setEmailOrPhone(e.target.value)}
                  placeholder="you@example.com"
                  dir="ltr"
                  className="h-11 rounded-xl border-[#D4AF37]/18 bg-[#1B1B1B] ps-11 text-sm text-[#F7F2E3] placeholder:text-[#CDB879]/35"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-[#E9D49A]">{t.password[language]}</label>
              <div className="relative">
                <Lock size={18} className="pointer-events-none absolute start-4 top-1/2 -translate-y-1/2 text-[#CDB879]/55" />
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  dir="ltr"
                  className="h-11 rounded-xl border-[#D4AF37]/18 bg-[#1B1B1B] ps-11 text-sm text-[#F7F2E3] placeholder:text-[#CDB879]/35"
                />
              </div>
            </div>

            {isLogin && (
              <div className="flex items-center justify-between px-1 text-xs">
                <label className="flex cursor-pointer items-center gap-2 font-medium text-[#D4C9A9]">
                  <input type="checkbox" className="h-4 w-4 rounded border border-[#D4AF37]/40 bg-transparent accent-[#D4AF37]" />
                  <span>{t.remember[language]}</span>
                </label>
                <button type="button" className="font-semibold text-[#D4AF37] transition hover:text-[#E4C766]">
                  {t.forgot[language]}
                </button>
              </div>
            )}

            <Button
              type="submit"
              className="mt-1 h-11 w-full rounded-xl bg-[#D4AF37] text-sm font-semibold text-[#0A0A0A] hover:bg-[#C49D2B]"
            >
              {isLogin ? t.signIn[language] : t.createAccount[language]}
            </Button>
          </form>
        </motion.div>

        <p className="mt-5 text-center text-xs text-[#B79F66]">{t.terms[language]}</p>
      </div>
    </div>
  );
}
