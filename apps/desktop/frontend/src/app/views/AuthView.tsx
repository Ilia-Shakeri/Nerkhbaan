import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Activity, ArrowLeft } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { api } from '../services/api';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';

export function AuthView() {
  const { language, login, toggleTheme, toggleLanguage, theme } = useAppContext();
  const isDark = theme === 'dark';
  const navigate = useNavigate();

  const [isLogin, setIsLogin] = useState(true);
  const [identifier, setIdentifier] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fullName, setFullName] = useState('');

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Nerkhbaan' },
    brandTagline: { fa: 'ردیابی و هشدار هوشمند قیمت', en: 'Smart price tracking & alerts' },
    login: { fa: 'ورود', en: 'Login' },
    signup: { fa: 'ثبت نام', en: 'Sign Up' },
    fullName: { fa: 'نام کامل', en: 'Full Name' },
    username: { fa: 'نام کاربری', en: 'Username' },
    email: { fa: 'ایمیل', en: 'Email' },
    identifier: { fa: 'ایمیل یا نام کاربری', en: 'Email or Username' },
    password: { fa: 'رمز عبور', en: 'Password' },
    remember: { fa: 'مرا به خاطر بسپار', en: 'Remember me' },
    forgot: { fa: 'فراموشی؟', en: 'Forgot?' },
    signIn: { fa: 'ورود به حساب', en: 'Sign In' },
    createAccount: { fa: 'ایجاد حساب', en: 'Create Account' },
    terms: { fa: 'با ادامه، شما با شرایط استفاده و حریم خصوصی موافقید', en: 'By continuing, you agree to our Terms of Service and Privacy Policy' },
    themeToggle: { fa: 'تغییر حالت', en: 'Toggle theme' },
    languageToggle: { fa: 'English', en: 'فارسی' },
    fillFields: { fa: 'لطفا همه فیلدها را کامل کنید', en: 'Please fill in all fields' },
    success: { fa: 'با موفقیت وارد شدید', en: 'Logged in successfully' },
    created: { fa: 'حساب کاربری با موفقیت ساخته شد', en: 'Account created successfully' },
    failed: { fa: 'عملیات ناموفق بود', en: 'Operation failed' },
    enterDemo: { fa: 'ورود نمایشی', en: 'Enter Demo' },
    demoHint: { fa: 'اگر دیتابیس یا بک اند آماده نیست، از ورود نمایشی استفاده کنید', en: 'Use demo access when backend/database is not ready' }
  };

  const allowDemoLogin = true;

  const handleDemoLogin = () => {
    localStorage.setItem('demoMode', 'true');
    login('demo_token');
    toast.success(t.success[language]);
    navigate('/');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLogin) {
        if (!identifier || !password) {
            toast.error(t.fillFields[language]);
            return;
        }
    } else {
        if (!fullName || !username || !email || !password) {
            toast.error(t.fillFields[language]);
            return;
        }
    }
    
    setIsSubmitting(true);
    try {
      if (isLogin) {
        const response = await api.auth.signin({
          username_or_email: identifier.trim(),
          password
        });
        login(response.access_token);
        toast.success(t.success[language]);
      } else {
        const response = await api.auth.signup({
          username: username.trim(),
          full_name: fullName.trim(),
          email: email.trim(),
          password
        });
        login(response.access_token);
        toast.success(t.created[language]);
      }
      navigate('/');
    } catch (error: any) {
      console.error('Auth error:', error);
      toast.error(error.message || t.failed[language]);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className={`relative h-screen overflow-hidden ${
        isDark ? 'bg-[#060606] text-[#F7F2E3]' : 'bg-[#FAF3E2] text-[#3B2E13]'
      }`}
    >
      <div
        className={`pointer-events-none absolute inset-0 ${
          isDark
            ? 'bg-[radial-gradient(circle_at_top,rgba(212,175,55,0.18),transparent_58%)]'
            : 'bg-[radial-gradient(circle_at_top,rgba(190,149,34,0.16),transparent_62%)]'
        }`}
      />

      <div className="absolute end-6 top-6 z-20 flex items-center gap-3">
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
          <Activity size={16} />
        </button>
      </div>

      <div className="relative z-10 flex h-full flex-col items-center justify-center p-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="mb-8 text-center"
        >
          <div className="mb-6 flex justify-center">
            <div className="relative">
              <div
                className={`absolute inset-0 blur-2xl ${
                  isDark ? 'bg-[#D4AF37]/20' : 'bg-[#D4AF37]/40'
                }`}
              />
              <div
                className={`relative flex h-20 w-20 items-center justify-center rounded-2xl border shadow-xl ${
                  isDark
                    ? 'border-[#D4AF37]/30 bg-[#121212]'
                    : 'border-[#D2B061]/50 bg-white'
                }`}
              >
                <Activity size={40} className={isDark ? 'text-[#D4AF37]' : 'text-[#8A6B20]'} />
              </div>
            </div>
          </div>
          <h1 className="mb-2 text-3xl font-black tracking-tight">{t.brandName[language]}</h1>
          <p className={isDark ? 'text-[#A0A0A0]' : 'text-[#8A6B20]'}>
            {t.brandTagline[language]}
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className={`mx-auto w-full max-w-xl rounded-3xl border p-4 shadow-[0_24px_60px_rgba(0,0,0,0.25)] ${
            isDark ? 'border-[#D4AF37]/25 bg-[#111111]/96' : 'border-[#D2B061]/45 bg-[#FFF9ED]/96'
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

          <form onSubmit={handleSubmit} className="space-y-4 p-2">
            {!isLogin && (
              <>
                <div className="space-y-2">
                  <label
                    className={`text-sm font-medium ${isDark ? 'text-[#CDB879]' : 'text-[#705822]'}`}
                  >
                    {t.fullName[language]}
                  </label>
                  <Input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="John Doe"
                    dir="auto"
                    className={`h-11 rounded-xl text-sm ${
                      isDark
                        ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                        : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                    }`}
                  />
                </div>
                <div className="space-y-2">
                  <label
                    className={`text-sm font-medium ${isDark ? 'text-[#CDB879]' : 'text-[#705822]'}`}
                  >
                    {t.username[language]}
                  </label>
                  <Input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="johndoe"
                    dir="ltr"
                    className={`h-11 rounded-xl text-sm ${
                      isDark
                        ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                        : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                    }`}
                  />
                </div>
                <div className="space-y-2">
                  <label
                    className={`text-sm font-medium ${isDark ? 'text-[#CDB879]' : 'text-[#705822]'}`}
                  >
                    {t.email[language]}
                  </label>
                  <Input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    dir="ltr"
                    className={`h-11 rounded-xl text-sm ${
                      isDark
                        ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                        : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                    }`}
                  />
                </div>
              </>
            )}

            {isLogin && (
              <div className="space-y-2">
                <label
                  className={`text-sm font-medium ${isDark ? 'text-[#CDB879]' : 'text-[#705822]'}`}
                >
                  {t.identifier[language]}
                </label>
                <div className="relative">
                  <Input
                    type="text"
                    value={identifier}
                    onChange={(e) => setIdentifier(e.target.value)}
                    placeholder="johndoe or you@example.com"
                    dir="ltr"
                    className={`h-11 rounded-xl text-sm ${
                      isDark
                        ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                        : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                    }`}
                  />
                </div>
              </div>
            )}

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label
                  className={`text-sm font-medium ${isDark ? 'text-[#CDB879]' : 'text-[#705822]'}`}
                >
                  {t.password[language]}
                </label>
                {isLogin && (
                  <button
                    type="button"
                    className={`text-xs hover:underline ${
                      isDark ? 'text-[#D4AF37]' : 'text-[#A38228]'
                    }`}
                  >
                    {t.forgot[language]}
                  </button>
                )}
              </div>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                dir="ltr"
                className={`h-11 rounded-xl text-sm ${
                  isDark
                    ? 'border-[#D4AF37]/18 bg-[#1B1B1B] text-[#F7F2E3] placeholder:text-[#CDB879]/35'
                    : 'border-[#D4AF37]/30 bg-[#FFFDF6] text-[#3B2E13] placeholder:text-[#B49549]/45'
                }`}
              />
            </div>

            <Button
              type="submit"
              disabled={isSubmitting}
              className={`h-12 w-full rounded-xl text-[15px] font-bold shadow-lg transition-all ${
                isDark
                  ? 'bg-[#D4AF37] text-[#0A0A0A] hover:bg-[#E8C556]'
                  : 'bg-[#D4AF37] text-[#0A0A0A] hover:bg-[#E5C254]'
              }`}
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
            
            {allowDemoLogin && (
              <p className={`text-center text-xs opacity-60 ${isDark ? 'text-[#A0A0A0]' : 'text-[#8A6B20]'}`}>
                  {t.demoHint[language]}
              </p>
            )}

          </form>

          <p
            className={`mt-6 text-center text-xs ${
              isDark ? 'text-[#A0A0A0]' : 'text-[#8A6B20]'
            }`}
          >
            {t.terms[language]}
          </p>
        </motion.div>
      </div>
    </div>
  );
}