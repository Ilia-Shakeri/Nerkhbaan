import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { User, Mail, Lock, CheckCircle2, XCircle, Sun, Moon, Languages, Eye, EyeOff } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { api } from '../services/api';
import { toast } from 'sonner';
import { useNavigate, Link } from 'react-router-dom';

export function AuthView() {
  const { language, toggleLanguage, login, theme, toggleTheme } = useAppContext();
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
  const [showPassword, setShowPassword] = useState(false);

  // Password live validation checks
  const hasLength = password.length >= 8;
  const hasUpper = /[A-Z]/.test(password);
  const hasLower = /[a-z]/.test(password);
  const hasNumSym = /[0-9!@#$%^&*(),.?":{}|<>\-_]/.test(password);
  const isPasswordValid = hasLength && hasUpper && hasLower && hasNumSym;

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Nerkhbaan' },
    footerText: { 
      fa: 'نرخ‌بان یک کیف پول نیست؛ بلکه پلتفرمی تخصصی برای ردیابی و هشدار هوشمند قیمت‌هاست.', 
      en: 'Nerkhbaan is not a wallet; it is a specialized platform for smart price tracking and alerts.' 
    },
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
    invalidPwdMsg: { fa: 'رمز عبور ضعیف است', en: 'Password is too weak' },
    networkError:  { fa: 'خطا در ارتباط با سرور. اتصال اینترنت خود را بررسی کنید.', en: 'Cannot reach server. Check your connection.' },
    badCredentials:{ fa: 'نام کاربری یا رمز عبور اشتباه است', en: 'Invalid username or password' },
    duplicate:     { fa: 'این ایمیل یا نام کاربری قبلاً ثبت شده است', en: 'Email or username already registered' },
  };

  const localizeError = (msg: string): string => {
    if (!msg || msg === 'Network Error' || msg.toLowerCase().startsWith('network')) return t.networkError[language];
    if (msg.toLowerCase().includes('invalid credentials')) return t.badCredentials[language];
    if (msg.toLowerCase().includes('already registered')) return t.duplicate[language];
    return msg;
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
        login(response.user);
        toast.success(t.success[language]);
      } else {
        const response = await api.auth.signup({
          username: username.trim(),
          full_name: fullName.trim(),
          email: email.trim(),
          password
        });
        login(response.user);
        toast.success(t.created[language]);
      }
      navigate('/');
    } catch (error: any) {
      const raw = error instanceof Error ? error.message : '';
      toast.error(localizeError(raw) || t.failed[language]);
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
    <div className={`flex h-screen overflow-hidden flex-col items-center justify-center p-4 transition-colors duration-500 ${isDark ? 'bg-[#060606]' : 'bg-[#FAF3E2]'}`}>
      
      {/* Header Controls */}
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
            className={`relative overflow-hidden rounded-[2rem] border shadow-2xl backdrop-blur-xl transition-all duration-300 ${
              isLogin ? 'p-6' : 'px-6 py-4'
            } ${
              isDark ? 'border-white/10 bg-[#0E0E0E]/80 shadow-black/50' : 'border-black/5 bg-white/80 shadow-[#D4AF37]/10'
            }`}
          >
            {/* Dynamically scale logo and text margins based on state to prevent viewport overflow */}
            <div className={`auth-brand-wrap flex flex-col items-center justify-center text-center transition-all duration-300 ${isLogin ? 'mb-4' : 'mb-2'}`}>
              <div className="auth-brand-logo-wrap relative z-10 mb-0 flex items-center justify-center">
                <img 
                  src="/icons/logo.png" 
                  alt="Nerkhbaan Logo" 
                  className={`auth-brand-logo object-contain drop-shadow-2xl transition-all duration-300 ${isLogin ? 'h-28 w-28' : 'h-16 w-16'}`} 
                />
              </div>
              <h1
                className={`auth-brand-title relative z-0 px-1 pt-0 transition-all duration-300 ${isLogin ? '-mt-3 pb-3' : '-mt-1 pb-1'} ${isRtl ? 'text-5xl font-normal leading-[1.8]' : 'text-4xl font-black tracking-tight'} ${isDark ? 'bg-gradient-to-r from-[#D4AF37] via-[#F3E2AB] to-[#D4AF37] bg-clip-text text-transparent' : 'bg-gradient-to-r from-[#3B2E13] via-[#8A6A23] to-[#3B2E13] bg-clip-text text-transparent'}`}
                style={isRtl ? { fontFamily: 'Noto_Nastaliq_Urdu, Noto Nastaliq Urdu, serif' } : undefined}
              >
                {t.brandName[language]}
              </h1>
            </div>

            {/* Dynamically adjust vertical gap spacing for inputs */}
            <form onSubmit={handleSubmit} className={`transition-all duration-300 ${isLogin ? 'space-y-4' : 'space-y-2'}`}>
              {!isLogin && (
                <>
                  <label className="block space-y-1">
                    <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.fullName[language]}</span>
                    <div className="relative">
                      <User size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#D4AF37]" />
                      <Input
                        type="text" value={fullName} onChange={(e) => setFullName(e.target.value)}
                        placeholder={t.fullNamePlaceholder[language]} required dir="ltr"
                        className={`h-11 rounded-2xl pl-11 pr-4 text-left text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                      />
                    </div>
                  </label>
                  <label className="block space-y-1">
                    <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.username[language]}</span>
                    <div className="relative">
                      <User size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#D4AF37]" />
                      <Input
                        type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                        placeholder={t.usernamePlaceholder[language]} required dir="ltr"
                        className={`h-11 rounded-2xl pl-11 pr-4 text-left text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                      />
                    </div>
                  </label>
                  <label className="block space-y-1">
                    <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.email[language]}</span>
                    <div className="relative">
                      <Mail size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#D4AF37]" />
                      <Input
                        type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                        placeholder={t.emailPlaceholder[language]} required dir="ltr"
                        className={`h-11 rounded-2xl pl-11 pr-4 text-left text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                      />
                    </div>
                  </label>
                </>
              )}

              {isLogin && (
                <label className="block space-y-2">
                  <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.identifierLabel[language]}</span>
                  <div className="relative">
                    <User size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#D4AF37]" />
                    <Input
                      type="text" value={identifier} onChange={(e) => setIdentifier(e.target.value)}
                      placeholder={t.identifierPlaceholder[language]} required dir="ltr"
                      className={`h-12 rounded-2xl pl-11 pr-4 text-left text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                    />
                  </div>
                </label>
              )}

              <label className={`block ${isLogin ? 'space-y-2' : 'space-y-1'}`}>
                <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.password[language]}</span>
                <div className="relative">
                  <Lock size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#D4AF37]" />
                  <Input
                    type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)}
                    required dir="ltr" placeholder={t.passwordPlaceholder[language]}
                    className={`${isLogin ? 'h-12' : 'h-11'} rounded-2xl pl-11 pr-14 text-left text-sm shadow-inner tracking-widest transition-all focus:ring-2 focus:ring-[#D4AF37]/50 [&::-ms-reveal]:hidden [&::-ms-clear]:hidden ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((prev) => !prev)}
                    tabIndex={-1}
                    className={`absolute right-2.5 top-1/2 -translate-y-1/2 flex h-8 w-8 items-center justify-center rounded-xl transition-all duration-200 hover:scale-105 active:scale-95 ${
                      isDark
                        ? 'bg-[#D4AF37]/12 text-[#D4AF37] hover:bg-[#D4AF37]/22 hover:shadow-[0_0_14px_rgba(212,175,55,0.32)]'
                        : 'bg-[#D4AF37]/18 text-[#8A6A23] hover:bg-[#D4AF37]/30 hover:shadow-[0_0_14px_rgba(212,175,55,0.22)]'
                    }`}
                  >
                    {showPassword ? <EyeOff size={15} strokeWidth={2.2} /> : <Eye size={15} strokeWidth={2.2} />}
                  </button>
                </div>
              </label>

              {isLogin && (
                <div className="flex w-full mt-2 justify-start">
                  <Link to="/forgot-password" className={`text-sm font-bold transition-all hover:opacity-80 hover:scale-[1.01] ${isDark ? 'text-[#D4AF37] hover:text-[#F3E2AB]' : 'text-[#8A6A23] hover:text-[#5E4714]'}`}>
                    {t.forgotPass[language]}
                  </Link>
                </div>
              )}

              {/* Password Validation Matrix - Renders only during registration flow */}
              {!isLogin && password.length > 0 && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="rounded-xl bg-black/5 p-3 dark:bg-white/5">
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div className={`flex items-center gap-1.5 transition-colors ${hasLength ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasLength ? <CheckCircle2 size={14} /> : <XCircle size={14} />} <span>{t.pwdLength[language]}</span>
                    </div>
                    <div className={`flex items-center gap-1.5 transition-colors ${hasUpper ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasUpper ? <CheckCircle2 size={14} /> : <XCircle size={14} />} <span>{t.pwdUpper[language]}</span>
                    </div>
                    <div className={`flex items-center gap-1.5 transition-colors ${hasLower ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasLower ? <CheckCircle2 size={14} /> : <XCircle size={14} />} <span>{t.pwdLower[language]}</span>
                    </div>
                    <div className={`flex items-center gap-1.5 transition-colors ${hasNumSym ? "text-emerald-500 font-bold" : isDark ? "text-gray-400" : "text-gray-500"}`}>
                      {hasNumSym ? <CheckCircle2 size={14} /> : <XCircle size={14} />} <span>{t.pwdNumSym[language]}</span>
                    </div>
                  </div>
                </motion.div>
              )}

              <Button
                type="submit"
                disabled={isSubmitting || (!isLogin && !isPasswordValid)}
                className={`w-full rounded-2xl text-sm font-bold transition-all duration-300 ${isLogin ? 'mt-6 h-12' : 'mt-4 h-11'} ${
                  (!isLogin && !isPasswordValid) ? 'opacity-50 cursor-not-allowed' : ''
                } ${
                  isDark 
                    ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB] text-black hover:shadow-[0_8px_32px_0_rgba(212,175,55,0.4)] hover:scale-[1.02]' 
                    : 'bg-gradient-to-r from-[#3B2E13] to-[#1F180A] text-white hover:shadow-[0_8px_32px_0_rgba(59,46,19,0.4)] hover:scale-[1.02]'
                }`}
              >
                {isSubmitting ? (
                  <div className="h-5 w-5 animate-spin rounded-full border-4 border-current border-t-transparent" />
                ) : (
                  isLogin ? t.submitLogin[language] : t.submitSignup[language]
                )}
              </Button>
              
              {registrationEnabled && (
                <div className={`${isLogin ? 'mt-6' : 'mt-3'} flex items-center justify-center gap-2 text-sm font-medium`}>
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

        {/* Global Professional Footer - Rendered strictly on the Login state */}
        {isLogin && (
          <div className="mt-8 flex w-full flex-col items-center justify-center border-t border-black/10 pt-5 dark:border-white/10">
            <p className={`text-center text-[13px] font-medium leading-relaxed transition-colors duration-300 ${isDark ? 'text-gray-400' : 'text-gray-500'}`} style={isRtl ? { fontFamily: 'Vazirmatn, sans-serif' } : undefined}>
              {t.footerText[language]}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
