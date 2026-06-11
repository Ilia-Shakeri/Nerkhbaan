import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { User, Mail, Lock, CheckCircle2, XCircle, Sun, Moon, Languages } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { api } from '../services/api';
import { toast } from 'sonner';
import { useNavigate, Link } from 'react-router-dom';

export function AuthView() {
  const { language, toggleLanguage, login, theme, toggleTheme } = useAppContext() as any;
  const isDark = theme === 'dark';
  const isRtl = language === 'fa';
  const navigate = useNavigate();

  // Feature flag check for public registration capabilities
  const registrationEnabled = import.meta.env.VITE_ENABLE_REGISTRATION !== 'false';

  const [isLogin, setIsLogin] = useState(true);
  const [identifier, setIdentifier] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fullName, setFullName] = useState('');

  // Password live validation checks
  const hasLength = password.length >= 8;
  const hasUpper = /[A-Z]/.test(password);
  const hasLower = /[a-z]/.test(password);
  const hasNumSym = /[0-9!@#$%^&*(),.?":{}|<>\-_]/.test(password);
  const isPasswordValid = hasLength && hasUpper && hasLower && hasNumSym;

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Nerkhbaan' },
    brandTagline: { fa: 'ردیابی و هشدار هوشمند قیمت', en: 'Smart price tracking & alerts' },
    login: { fa: 'ورود', en: 'Login' },
    signup: { fa: 'ثبت نام', en: 'Sign up' },
    submitLogin: { fa: 'ورود به حساب', en: 'Sign In' },
    submitSignup: { fa: 'ایجاد حساب کاربری', en: 'Create Account' },
    identifierLabel: { fa: 'نام کاربری یا ایمیل', en: 'Username or Email' },
    identifierPlaceholder: { fa: 'username یا name@example.com', en: 'username or name@example.com' },
    username: { fa: 'نام کاربری', en: 'Username' },
    usernamePlaceholder: { fa: 'ali', en: 'john' },
    email: { fa: 'ایمیل', en: 'Email' },
    emailPlaceholder: { fa: 'name@example.com', en: 'name@example.com' },
    password: { fa: 'رمز عبور', en: 'Password' },
    passwordPlaceholder: { fa: '********', en: '********' },
    fullName: { fa: 'نام و نام خانوادگی', en: 'Full Name' },
    fullNamePlaceholder: { fa: 'مثال: علی رضایی', en: 'e.g., John Doe' },
    forgotPass: { fa: 'رمز عبور خود را فراموش کرده‌اید؟', en: 'Forgot your password?' },
    noAccount: { fa: 'حساب کاربری ندارید؟', en: "Don't have an account?" },
    hasAccount: { fa: 'قبلا ثبت نام کرده‌اید؟', en: 'Already have an account?' },
    success: { fa: 'با موفقیت وارد شدید', en: 'Successfully logged in' },
    created: { fa: 'حساب کاربری با موفقیت ایجاد شد', en: 'Account created successfully' },
    failed: { fa: 'خطا در ارتباط با سرور', en: 'Server connection failed' },
    pwdLength: { fa: 'حداقل ۸ کاراکتر', en: 'At least 8 characters' },
    pwdUpper: { fa: 'یک حرف بزرگ', en: 'Uppercase letter' },
    pwdLower: { fa: 'یک حرف کوچک', en: 'Lowercase letter' },
    pwdNumSym: { fa: 'عدد یا نماد', en: 'Number or Symbol' },
    invalidPwdMsg: { fa: 'رمز عبور ضعیف است', en: 'Password is too weak' }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLogin && !isPasswordValid) {
        toast.error(t.invalidPwdMsg[language]);
        return;
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
      const message = error instanceof Error ? error.message : t.failed[language];
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  // 3D Flip Animation configuration
  const flipVariants = {
    initial: { rotateY: isRtl ? -90 : 90, opacity: 0 },
    animate: { rotateY: 0, opacity: 1, transition: { duration: 0.4, ease: "easeOut" } },
    exit: { rotateY: isRtl ? 90 : -90, opacity: 0, transition: { duration: 0.3, ease: "easeIn" } }
  };

  return (
    <div className={`flex min-h-screen flex-col items-center justify-center p-6 transition-colors duration-500 ${isDark ? 'bg-[#060606]' : 'bg-[#FAF3E2]'}`}>
      <div className="absolute top-6 left-6 flex items-center gap-3">
        <button onClick={toggleLanguage} className={`flex h-10 items-center justify-center rounded-2xl px-4 text-xs font-bold shadow-sm transition-all hover:scale-105 ${isDark ? 'bg-white/5 text-[#E8D9AE] hover:bg-white/10' : 'bg-black/5 text-[#6B4E16] hover:bg-black/10'}`}>
          <Languages size={16} className="me-2" />
          {language === 'fa' ? 'English' : 'فارسی'}
        </button>
        <button onClick={toggleTheme} className={`flex h-10 w-10 items-center justify-center rounded-2xl shadow-sm transition-all hover:scale-105 ${isDark ? 'bg-white/5 text-[#E8D9AE] hover:bg-white/10' : 'bg-black/5 text-[#6B4E16] hover:bg-black/10'}`}>
          {isDark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </div>

      <div className="w-full max-w-md perspective-1000">
        <AnimatePresence mode="wait">
          <motion.div
            key={isLogin ? 'login' : 'signup'}
            variants={flipVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className={`relative overflow-hidden rounded-[2rem] border p-8 shadow-2xl backdrop-blur-xl ${
              isDark ? 'border-white/10 bg-[#0E0E0E]/80 shadow-black/50' : 'border-black/5 bg-white/80 shadow-[#D4AF37]/10'
            }`}
          >
            <div className="mb-8 flex flex-col items-center justify-center text-center">
              {/* Reduced mb-6 to mb-2 to tighten the space between logo and text */}
              <div className="mb-2 flex items-center justify-center">
                {/* Note: use src="/icons/logo.png" for Web, and src={logo} for Desktop based on your setup */}
                <img src="/icons/logo.png" alt="Nerkhbaan Logo" className="h-28 w-28 object-contain drop-shadow-2xl" />
              </div>
              
              <h1
                className={`tracking-tight pb-2 px-1 ${isRtl ? 'text-6xl font-black' : 'text-5xl font-black'} ${isDark ? 'bg-gradient-to-r from-[#D4AF37] via-[#F3E2AB] to-[#D4AF37] bg-clip-text text-transparent' : 'bg-gradient-to-r from-[#3B2E13] via-[#8A6A23] to-[#3B2E13] bg-clip-text text-transparent'}`}
                style={isRtl ? { fontFamily: 'Vazirmatn, sans-serif' } : undefined}
              >
                {t.brandName[language]}
              </h1>
              
              <p className={`mt-0 text-base font-semibold ${isDark ? 'text-[#CDB879]' : 'text-[#8A6A23]'}`} style={isRtl ? { fontFamily: 'Vazirmatn, sans-serif' } : undefined}>
                {t.brandTagline[language]}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              {!isLogin && (
                <>
                  <label className="block space-y-2">
                    <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.fullName[language]}</span>
                    <div className="relative">
                      <User size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                      <Input
                        type="text" value={fullName} onChange={(e) => setFullName(e.target.value)}
                        placeholder={t.fullNamePlaceholder[language]} required
                        className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                      />
                    </div>
                  </label>
                  <label className="block space-y-2">
                    <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.username[language]}</span>
                    <div className="relative">
                      <User size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                      <Input
                        type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                        placeholder={t.usernamePlaceholder[language]} required dir="ltr"
                        className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                      />
                    </div>
                  </label>
                  <label className="block space-y-2">
                    <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.email[language]}</span>
                    <div className="relative">
                      <Mail size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                      <Input
                        type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                        placeholder={t.emailPlaceholder[language]} required dir="ltr"
                        className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                      />
                    </div>
                  </label>
                </>
              )}

              {isLogin && (
                <label className="block space-y-2">
                  <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.identifierLabel[language]}</span>
                  <div className="relative">
                    <User size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                    <Input
                      type="text" value={identifier} onChange={(e) => setIdentifier(e.target.value)}
                      placeholder={t.identifierPlaceholder[language]} required dir="ltr"
                      className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                    />
                  </div>
                </label>
              )}

              <label className="block space-y-2">
                <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.password[language]}</span>
                <div className="relative">
                  <Lock size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                  <Input
                    type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                    required dir="ltr" placeholder={t.passwordPlaceholder[language]}
                    className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner tracking-widest transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                  />
                </div>
              </label>

              {isLogin && (
                <div className={`flex w-full mt-2 justify-start`}>
                  <Link to="/forgot-password" className={`text-sm font-bold transition-all hover:opacity-80 hover:scale-[1.01] ${isDark ? 'text-[#D4AF37] hover:text-[#F3E2AB]' : 'text-[#8A6A23] hover:text-[#5E4714]'}`}>
                    {t.forgotPass[language]}
                  </Link>
                </div>
              )}

              {!isLogin && password.length > 0 && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="rounded-xl bg-black/5 p-4 dark:bg-white/5">
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className={`flex items-center gap-2 transition-colors ${hasLength ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasLength ? <CheckCircle2 size={16} /> : <XCircle size={16} />} <span>{t.pwdLength[language]}</span>
                    </div>
                    <div className={`flex items-center gap-2 transition-colors ${hasUpper ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasUpper ? <CheckCircle2 size={16} /> : <XCircle size={16} />} <span>{t.pwdUpper[language]}</span>
                    </div>
                    <div className={`flex items-center gap-2 transition-colors ${hasLower ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasLower ? <CheckCircle2 size={16} /> : <XCircle size={16} />} <span>{t.pwdLower[language]}</span>
                    </div>
                    <div className={`flex items-center gap-2 transition-colors ${hasNumSym ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasNumSym ? <CheckCircle2 size={16} /> : <XCircle size={16} />} <span>{t.pwdNumSym[language]}</span>
                    </div>
                  </div>
                </motion.div>
              )}

              <Button
                type="submit"
                disabled={isSubmitting || (!isLogin && !isPasswordValid)}
                className={`mt-6 h-12 w-full rounded-2xl text-sm font-bold transition-all duration-300 ${
                  (!isLogin && !isPasswordValid) ? 'opacity-50 cursor-not-allowed' : ''
                } ${
                  isDark 
                    ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB] text-black hover:shadow-[0_8px_32px_0_rgba(212,175,55,0.4)] hover:scale-[1.02]' 
                    : 'bg-gradient-to-r from-[#3B2E13] to-[#1F180A] text-white hover:shadow-[0_8px_32px_0_rgba(59,46,19,0.4)] hover:scale-[1.02]'
                }`}
              >
                {isSubmitting ? (
                  <div className="h-6 w-6 animate-spin rounded-full border-4 border-current border-t-transparent" />
                ) : (
                  isLogin ? t.submitLogin[language] : t.submitSignup[language]
                )}
              </Button>
              
              {/* Conditional rendering for the registration toggle based on environment variable */}
              {registrationEnabled && (
                <div className="mt-6 flex items-center justify-center gap-2 text-sm font-medium">
                  <span className={isDark ? 'text-gray-400' : 'text-gray-600'}>
                    {isLogin ? t.noAccount[language] : t.hasAccount[language]}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setIsLogin(!isLogin);
                      setPassword('');
                    }}
                    className={`font-bold transition-all hover:opacity-80 hover:scale-[1.01] ${isDark ? 'text-[#D4AF37] hover:text-[#F3E2AB]' : 'text-[#8A6A23] hover:text-[#5E4714]'}`}
                  >
                    {isLogin ? t.signup[language] : t.login[language]}
                  </button>
                </div>
              )}
            </form>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}