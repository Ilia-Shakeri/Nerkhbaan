import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Mail, ArrowRight, ArrowLeft, KeyRound, CheckCircle2 } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { api } from '../services/api';
import { toast } from 'sonner';
import { Link, useNavigate } from 'react-router-dom';
import { LegalLinks } from '../components/LegalLinks';

export function ForgotPasswordView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';
  const isRtl = language === 'fa';
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [step, setStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const errorRef = useRef<HTMLDivElement>(null);

  const t = {
    // Replaced the simple tagline with a descriptive footer message
    footerText: { 
      fa: 'نرخ‌بان یک کیف پول نیست؛ بلکه پلتفرمی تخصصی برای ردیابی و هشدار هوشمند قیمت‌هاست.', 
      en: 'Nerkhbaan is not a wallet; it is a specialized platform for smart price tracking and alerts.' 
    },
    backToLogin: { fa: 'بازگشت به ورود', en: 'Back to login' },
    title1: { fa: 'بازیابی رمز عبور', en: 'Forgot Password' },
    desc1: { fa: 'ایمیل خود را وارد کنید تا کد بازیابی برای شما ارسال شود.', en: 'Enter your email address to receive a recovery code.' },
    emailLabel: { fa: 'ایمیل شما', en: 'Your Email' },
    emailPlaceholder: { fa: 'name@example.com', en: 'name@example.com' },
    sendCode: { fa: 'ارسال کد تایید', en: 'Send Recovery Code' },
    title2: { fa: 'تایید کد و تغییر رمز', en: 'Verify & Reset Password' },
    desc2: { fa: 'کد ارسال شده به ایمیل خود و رمز عبور جدید را وارد کنید.', en: 'Enter the code sent to your email and your new password.' },
    codeLabel: { fa: 'کد تایید ۶ رقمی', en: '6-digit Recovery Code' },
    codePlaceholder: { fa: '123456', en: '123456' },
    newPassLabel: { fa: 'رمز جدید: ۱۰ تا ۱۲۸ کاراکتر، حرف کوچک، بزرگ و عدد', en: 'New password: 10–128 characters, lower case, upper case and digit' },
    newPassPlaceholder: { fa: '••••••••', en: '••••••••' },
    resetBtn: { fa: 'تغییر رمز عبور', en: 'Reset Password' },
    title3: { fa: 'رمز عبور تغییر کرد!', en: 'Password Reset Successful!' },
    desc3: { fa: 'اکنون می‌توانید با رمز عبور جدید خود وارد شوید.', en: 'You can now log in with your new password.' },
    goToLogin: { fa: 'ورود به حساب', en: 'Go to Login' }
  };

  const readableError = (error: unknown, fallbackFa: string, fallbackEn: string) => {
    const message = error instanceof Error ? error.message : '';
    if (language === 'fa') return /[\u0600-\u06ff]/.test(message) ? message : fallbackFa;
    return message || fallbackEn;
  };

  useEffect(() => {
    if (formError) errorRef.current?.focus();
  }, [formError]);

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setIsSubmitting(true);
    try {
      // Connects to existing endpoint logic
      await api.auth.forgotPassword(email);
      toast.success(language === 'fa' ? 'اگر حساب واجد شرایط باشد، کد بازیابی ارسال می‌شود.' : 'If the account is eligible, a recovery code will be sent.');
      setStep(2);
    } catch (error: any) {
      const message = readableError(error, 'ارسال کد انجام نشد. دوباره تلاش کنید.', 'The recovery code could not be sent. Try again.');
      setFormError(message);
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setIsSubmitting(true);
    try {
      await api.auth.resetPassword({ email, code: code.trim(), new_password: newPassword });
      setStep(3);
    } catch (error: any) {
      const message = readableError(error, 'کد نامعتبر یا منقضی شده است', 'Invalid or expired code');
      setFormError(message);
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const flipVariants = {
    initial: { rotateY: isRtl ? -90 : 90, opacity: 0 },
    animate: { rotateY: 0, opacity: 1, transition: { duration: 0.4, ease: "easeOut" } },
    exit: { rotateY: isRtl ? 90 : -90, opacity: 0, transition: { duration: 0.3, ease: "easeIn" } }
  };

  return (
    <div className={`flex min-h-dvh flex-col items-center justify-center overflow-x-hidden overflow-y-auto p-6 transition-colors duration-500 ${isDark ? 'bg-[#060606]' : 'bg-[#FAF3E2]'}`} style={{ paddingTop: 'max(1.5rem, env(safe-area-inset-top))', paddingBottom: 'max(1.5rem, env(safe-area-inset-bottom))' }}>
      <div className="w-full max-w-md perspective-1000">
        <div className="mb-6 flex justify-start">
            <Link to="/auth" className={`flex items-center gap-2 text-sm font-bold transition-all hover:opacity-80 hover:scale-[1.01] ${isDark ? 'text-[#D4AF37] hover:text-[#F3E2AB]' : 'text-[#8A6A23] hover:text-[#5E4714]'}`}>
                {isRtl ? <ArrowRight size={16} /> : <ArrowLeft size={16} />}
                {t.backToLogin[language]}
            </Link>
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            variants={flipVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className={`relative overflow-hidden rounded-[2rem] border p-8 shadow-2xl backdrop-blur-xl ${
              isDark ? 'border-white/10 bg-[#0E0E0E]/80 shadow-black/50' : 'border-black/5 bg-white/80 shadow-[#D4AF37]/10'
            }`}
          >
            <div className="mb-8 flex flex-col items-center justify-center text-center">
              {/* Increased size to h-28 w-28 and added z-10 to stay above the title */}
              <div className="relative z-10 mb-0 flex items-center justify-center">
                <img src="/icons/logo.png" alt="Nerkhbaan Logo" className="h-28 w-28 object-contain drop-shadow-2xl" />
              </div>
              
              {/* Replaced IranNastaliq with the unified Noto Nastaliq font, negative top margin (-mt-3) brings it close */}
              {step === 1 && (
                <>
                  <h1 
                    className={`relative z-0 -mt-3 px-1 pb-3 pt-0 ${isRtl ? 'text-4xl font-normal leading-[1.8]' : 'text-3xl font-black tracking-tight'} ${isDark ? 'bg-gradient-to-r from-[#D4AF37] via-[#F3E2AB] to-[#D4AF37] bg-clip-text text-transparent' : 'bg-gradient-to-r from-[#8A6A23] via-[#5E4714] to-[#8A6A23] bg-clip-text text-transparent'}`}
                    style={isRtl ? { fontFamily: 'Noto_Nastaliq_Urdu, Noto Nastaliq Urdu, serif' } : undefined}
                  >
                    {t.title1[language]}
                  </h1>
                  <p className={`mt-2 text-sm font-medium ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>{t.desc1[language]}</p>
                </>
              )}
              {step === 2 && (
                <>
                  <h1 
                    className={`relative z-0 -mt-3 px-1 pb-3 pt-0 ${isRtl ? 'text-4xl font-normal leading-[1.8]' : 'text-3xl font-black tracking-tight'}`}
                    style={isRtl ? { fontFamily: 'Noto_Nastaliq_Urdu, Noto Nastaliq Urdu, serif' } : undefined}
                  >
                    {t.title2[language]}
                  </h1>
                  <p className={`mt-2 text-sm font-medium ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>{t.desc2[language]}</p>
                </>
              )}
              {step === 3 && (
                <>
                  <h1 
                    className={`relative z-0 -mt-3 px-1 pb-3 pt-0 text-emerald-500 ${isRtl ? 'text-4xl font-normal leading-[1.8]' : 'text-3xl font-black tracking-tight'}`}
                    style={isRtl ? { fontFamily: 'Noto_Nastaliq_Urdu, Noto Nastaliq Urdu, serif' } : undefined}
                  >
                    {t.title3[language]}
                  </h1>
                  <p className={`mt-2 text-sm font-medium ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>{t.desc3[language]}</p>
                </>
              )}
            </div>

            {step === 1 && (
                <form onSubmit={handleSendCode} className="space-y-5">
                    <label className="block space-y-2">
                        <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.emailLabel[language]}</span>
                        <div className="relative">
                            <Mail size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 text-[#D4AF37]`} />
                            <Input
                                name="email" autoComplete="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                                placeholder={t.emailPlaceholder[language]} required dir="ltr"
                                className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                            />
                        </div>
                    </label>
                    {formError && (
                      <div ref={errorRef} tabIndex={-1} role="alert" className={`rounded-xl border px-3 py-2 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-red-400 ${isDark ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-red-300 bg-red-50 text-red-700'}`}>
                        {formError}
                      </div>
                    )}
                    <Button
                        type="submit" disabled={isSubmitting}
                        aria-label={t.sendCode[language]} aria-busy={isSubmitting}
                        className={`mt-6 h-12 w-full rounded-2xl text-sm font-bold transition-all duration-300 ${
                        isDark 
                            ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB] text-black shadow-[0_8px_32px_0_rgba(212,175,55,0.25)] hover:shadow-[0_8px_32px_0_rgba(212,175,55,0.4)] hover:scale-[1.02]' 
                            : 'bg-gradient-to-r from-[#3B2E13] to-[#1F180A] text-white shadow-[0_8px_32px_0_rgba(59,46,19,0.25)] hover:shadow-[0_8px_32px_0_rgba(59,46,19,0.4)] hover:scale-[1.02]'
                        }`}
                    >
                        {isSubmitting ? <div className="h-6 w-6 animate-spin rounded-full border-4 border-current border-t-transparent" /> : t.sendCode[language]}
                    </Button>
                </form>
            )}

            {step === 2 && (
                <form onSubmit={handleResetPassword} className="space-y-5">
                    <label className="block space-y-2">
                        <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.codeLabel[language]}</span>
                        <div className="relative">
                            <KeyRound size={18} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#D4AF37]" />
                            <Input
                                name="recovery-code" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" type="text" value={code} onChange={(e) => setCode(e.target.value)}
                                placeholder={t.codePlaceholder[language]} required dir="ltr"
                                className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 tracking-widest font-mono font-bold ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                            />
                        </div>
                    </label>
                    <label className="block space-y-2">
                        <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.newPassLabel[language]}</span>
                        <div className="relative">
                            <KeyRound size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 text-[#D4AF37]`} />
                            <Input
                                name="new-password" autoComplete="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                                placeholder={t.newPassPlaceholder[language]} required dir="ltr"
                                passwordToggleLabels={{
                                  show: language === 'fa' ? 'نمایش رمز عبور جدید' : 'Show new password',
                                  hide: language === 'fa' ? 'پنهان کردن رمز عبور جدید' : 'Hide new password',
                                }}
                                className={`h-12 rounded-2xl pl-11 pr-14 text-left text-sm shadow-inner tracking-widest transition-all focus:ring-2 focus:ring-[#D4AF37]/50 [&::-ms-reveal]:hidden [&::-ms-clear]:hidden ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-500' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                            />
                        </div>
                    </label>
                    {formError && (
                      <div ref={errorRef} tabIndex={-1} role="alert" className={`rounded-xl border px-3 py-2 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-red-400 ${isDark ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-red-300 bg-red-50 text-red-700'}`}>
                        {formError}
                      </div>
                    )}
                    <Button
                        type="submit" disabled={isSubmitting || newPassword.length < 10 || newPassword.length > 128 || !/[a-z]/.test(newPassword) || !/[A-Z]/.test(newPassword) || !/[0-9]/.test(newPassword)}
                        aria-label={t.resetBtn[language]} aria-busy={isSubmitting}
                        className={`mt-6 h-12 w-full rounded-2xl text-sm font-bold transition-all duration-300 ${
                        isDark 
                            ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB] text-black shadow-[0_8px_32px_0_rgba(212,175,55,0.25)] hover:shadow-[0_8px_32px_0_rgba(212,175,55,0.4)] hover:scale-[1.02]' 
                            : 'bg-gradient-to-r from-[#3B2E13] to-[#1F180A] text-white shadow-[0_8px_32px_0_rgba(59,46,19,0.25)] hover:shadow-[0_8px_32px_0_rgba(59,46,19,0.4)] hover:scale-[1.02]'
                        }`}
                    >
                        {isSubmitting ? <div className="h-6 w-6 animate-spin rounded-full border-4 border-current border-t-transparent" /> : t.resetBtn[language]}
                    </Button>
                </form>
            )}

            {step === 3 && (
                <div className="flex flex-col items-center">
                    <CheckCircle2 size={64} className="mb-6 text-emerald-500" />
                    <Button
                        onClick={() => navigate('/auth')}
                        className={`h-12 w-full rounded-2xl text-sm font-bold transition-all duration-300 ${
                        isDark 
                            ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB] text-black shadow-[0_8px_32px_0_rgba(212,175,55,0.25)] hover:shadow-[0_8px_32px_0_rgba(212,175,55,0.4)] hover:scale-[1.02]' 
                            : 'bg-gradient-to-r from-[#3B2E13] to-[#1F180A] text-white shadow-[0_8px_32px_0_rgba(59,46,19,0.25)] hover:shadow-[0_8px_32px_0_rgba(59,46,19,0.4)] hover:scale-[1.02]'
                        }`}
                    >
                        {t.goToLogin[language]}
                    </Button>
                </div>
            )}
          </motion.div>
        </AnimatePresence>
        
        {/* Global Professional Footer */}
        <p className={`mt-4 text-sm ${isDark ? 'text-[#E8D9AE]' : 'text-[#3B2E13]'}`}>{language === 'fa' ? 'ایمیل فقط برای بازیابی درخواستی شما پردازش می‌شود؛ اجازه بازاریابی نیست.' : 'Your email is processed for the recovery you request, not marketing.'}</p>
        <LegalLinks />
        <div className={`mt-8 flex w-full flex-col items-center justify-center border-t border-black/10 pt-5 dark:border-white/10`}>
          <p className={`text-center text-[13px] font-medium leading-relaxed transition-colors duration-300 ${isDark ? 'text-gray-400' : 'text-gray-500'}`} style={isRtl ? { fontFamily: 'Vazirmatn, sans-serif' } : undefined}>
            {t.footerText[language]}
          </p>
        </div>

      </div>
    </div>
  );
}
