// frontend/src/app/views/AuthView.tsx

import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Moon, Sun, User, Mail, Lock } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
import { WindowTitleBar } from '../components/WindowTitleBar';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { toast } from 'sonner';
import logo from '../../logo/logo.png';
import { signin, signup } from '../services/api';

export function AuthView() {
  const navigate = useNavigate();
  const { login, language, theme, toggleTheme, toggleLanguage } = useAppContext();
  const isProductionBuild =
    import.meta.env.PROD || import.meta.env.MODE === 'production';
  const allowDemoLogin = !isProductionBuild && import.meta.env.VITE_ENABLE_DEMO_LOGIN !== 'false';

  const [isLogin, setIsLogin] = useState(true);
  const [fullName, setFullName] = useState('');
  const [emailOrPhone, setEmailOrPhone] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Nerkhban' },
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
    created: { fa: 'حساب کاربری با موفقیت ساخته شد', en: 'Account created successfully' },
    failed: { fa: 'ورود ناموفق بود', en: 'Login failed' },
    enterDemo: { fa: 'ورود نمایشی', en: 'Enter Demo' },
    demoHint: {
      fa: 'اگر دیتابیس یا بک اند آماده نیست، از ورود نمایشی استفاده کنید',
      en: 'Use demo access when backend/database is not ready'
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!emailOrPhone || !password || (!isLogin && !fullName)) {
      toast.error(t.fillFields[language]);
      return;
    }

    setIsSubmitting(true);
    try {
      if (isLogin) {
        const response = await signin({ email: emailOrPhone.trim(), password });
        login(response.access_token);
        toast.success(t.success[language]);
      } else {
        const response = await signup({
          full_name: fullName.trim(),
          email: emailOrPhone.trim(),
          password
        });
        login(response.access_token);
        toast.success(t.created[language]);
      }

      navigate('/');
    } catch (error) {
      console.error('Auth error:', error);
      const message = error instanceof Error ? error.message : t.failed[language];
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const isDark = theme === 'dark';
  const handleDemoLogin = () => {
    login('demo-local-token');
    localStorage.setItem('demoMode', 'true');
    toast.success(language === 'fa' ? 'با حساب نمایشی وارد شدید' : 'Entered with demo account');
    navigate('/');
  };

  return (
    <div
      className={`relative h-screen overflow-hidden ${
        isDark ? 'bg-[#060606] text-[#F7F2E3]' : 'bg-[#FAF3E2] text-[#3B2E13]'
      }`}
    >
      <WindowTitleBar theme={theme} />
      <div
        className={`pointer-events-none absolute inset-0 ${
          isDark
            ? 'bg-[radial-gradient(circle_at_top,rgba(212,175,55,0.18),transparent_58%)]'
            : 'bg-[radial-gradient(circle_at_top,rgba(190,149,34,0.16),transparent_62%)]'
        }`}
      />

      <div className="titlebar-no-drag absolute end-6 top-14 z-20 flex items-center gap-3">
        <button
          type="button"
          aria-label={t.languageToggle[language]}
          onClick={toggleLanguage}
          className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
            isDark
              ? 'border-[#D4AF37]/35 bg-[#121212] text-[#D9BE66] hover:bg-[#1A1A1A]'
              : 'border-[#C8A347]/45 bg-[#FDF7EA] text-[#805F14] hover:bg-[#F3E5C4]'
          }`}
        >
          <span>{t.languageToggle[language]}</span>
        </button>
        <button
          type="button"
          aria-label={t.themeToggle[language]}
          onClick={toggleTheme}
          className={`rounded-full border p-2 transition ${
            isDark
              ? 'border-[#D4AF37]/35 bg-[#121212] text-[#D9BE66] hover:bg-[#1A1A1A]'
              : 'border-[#C8A347]/45 bg-[#FDF7EA] text-[#805F14] hover:bg-[#F3E5C4]'
          }`}
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </div>

      <div className="relative z-10 mx-auto flex h-[calc(100vh-2.5rem)] w-full max-w-5xl -translate-y-4 flex-col items-center justify-center px-6 pt-4">
        <div className="mb-5 flex flex-col items-center text-center">
          <img
            src={logo}
            alt={t.brandName[language]}
            className="mb-1 h-[120px] w-[120px] object-contain md:h-[145px] md:w-[145px]"
          />
        </div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className={`mx-auto w-full max-w-xl rounded-3xl border p-4 shadow-[0_24px_60px_rgba(0,0,0,0.25)] ${
            isDark
              ? 'border-[#D4AF37]/25 bg-[#111111]/96'
              : 'border-[#D2B061]/45 bg-[#FFF9ED]/96'
          }`}
        >
          <div
            className={`mb-4 grid grid-cols-2 rounded-xl p-1 ${
              isDark ? 'bg-[#171717]' : 'bg-[#F4E7C7]'
            }`}
          >
            <button
              type="button"
              onClick={() => setIsLogin(true)}
              className={`h-10 rounded-lg text-sm font-semibold transition-all duration-300 ${
                isLogin
                  ? 'bg-[#D4AF37] text-[#0A0A0A] shadow-[0_4px_14px_rgba(212,175,55,0.35)]'
                  : isDark
                    ? 'text-[#B9A46A]'
                    : 'text-[#7F641C]'
              }`}
            >
              {t.login[language]}
            </button>
            <button
              type="button"
              onClick={() => setIsLogin(false)}
              className={`h-10 rounded-lg text-sm font-semibold transition-all duration-300 ${
                !isLogin
                  ? 'bg-[#D4AF37] text-[#0A0A0A] shadow-[0_4px_14px_rgba(212,175,55,0.35)]'
                  : isDark
                    ? 'text-[#B9A46A]'
                    : 'text-[#7F641C]'
              }`}
            >
              {t.signup[language]}
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            {!isLogin && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                className="space-y-2"
              >
                <label className={`text-sm font-medium ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>
                  {t.fullName[language]}
                </label>
                <div className="relative">
                  <User size={18} className={`pointer-events-none absolute start-4 top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                  <Input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="John Doe"
                    dir="ltr"
                    className={`h-11 rounded-xl ps-11 text-sm ${
                      isDark
                        ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                        : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                    }`}
                  />
                </div>
              </motion.div>
            )}

            <div className="space-y-2">
              <label className={`text-sm font-medium ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>
                {t.email[language]}
              </label>
              <div className="relative">
                <Mail size={18} className={`pointer-events-none absolute start-4 top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                <Input
                  type="text"
                  value={emailOrPhone}
                  onChange={(e) => setEmailOrPhone(e.target.value)}
                  placeholder="you@example.com"
                  dir="ltr"
                  className={`h-11 rounded-xl ps-11 text-sm ${
                    isDark
                      ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                      : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                  }`}
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className={`text-sm font-medium ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>
                {t.password[language]}
              </label>
              <div className="relative">
                <Lock size={18} className={`pointer-events-none absolute start-4 top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  dir="ltr"
                  className={`h-11 rounded-xl ps-11 text-sm ${
                    isDark
                      ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                      : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                  }`}
                />
              </div>
            </div>

            {isLogin && (
              <div className="flex items-center justify-between px-1 text-xs">
                <label className={`flex cursor-pointer items-center gap-2 font-medium ${isDark ? 'text-[#D4C9A9]' : 'text-[#765A18]'}`}>
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
              disabled={isSubmitting}
              className="mt-1 h-11 w-full rounded-xl bg-[#D4AF37] text-sm font-semibold text-[#0A0A0A] transition-all duration-300 hover:bg-[#C49D2B] hover:shadow-[0_8px_22px_rgba(212,175,55,0.35)]"
            >
              {isSubmitting
                ? language === 'fa'
                  ? 'در حال پردازش...'
                  : 'Processing...'
                : isLogin
                  ? t.signIn[language]
                  : t.createAccount[language]}
            </Button>

            {allowDemoLogin && (
              <button
                type="button"
                onClick={handleDemoLogin}
                className={`h-10 w-full rounded-xl border text-sm font-semibold transition ${
                  isDark
                    ? 'border-[#D4AF37]/30 bg-[#171717] text-[#D9BE66] hover:bg-[#1F1F1F]'
                    : 'border-[#C8A347]/45 bg-[#FDF7EA] text-[#805F14] hover:bg-[#F3E5C4]'
                }`}
              >
                {t.enterDemo[language]}
              </button>
            )}
          </form>
        </motion.div>

        <p className={`mt-3 text-center text-xs ${isDark ? 'text-[#B79F66]' : 'text-[#8C7028]'}`}>
          {t.terms[language]}
        </p>
        {allowDemoLogin && (
          <p className={`mt-1 text-center text-[11px] ${isDark ? 'text-[#9A8653]' : 'text-[#9C7C34]'}`}>
            {t.demoHint[language]}
          </p>
        )}
      </div>
    </div>
  );
}
