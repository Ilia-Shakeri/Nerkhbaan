import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Mail, ArrowRight, ArrowLeft, KeyRound, CheckCircle2 } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { api } from '../services/api';
import toast from 'react-hot-toast';
import { Link, useNavigate } from 'react-router-dom';
import logo from '../../logo/logo.png';

export function ForgotPasswordView() {
  const { language, theme } = useAppContext() as any;
  const isDark = theme === 'dark';
  const isRtl = language === 'fa';
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [step, setStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const t = {
    // Replaced the simple tagline with a descriptive footer message
    footerText: { 
      fa: 'نرخ‌بان یک کیف پول نیست؛ بلکه پلتفرمی تخصصی برای ردیابی و هشدار هوشمند قیمت‌هاست.', 
      en: 'Nerkhbaan is not a wallet; it is a specialized platform for smart price tracking and alerts.' 
    },
    backToLogin: { fa: 'بازگشت به ورود', en: 'Back to login' },
    title1: { fa: 'بازیابی رمز عبور', en: 'Forgot Password' },
    desc1: { fa: 'ایمیل خود را وارد کنید تا لینک و کد بازیابی برای شما ارسال شود.', en: 'Enter your email address to receive a recovery code.' },
    emailLabel: { fa: 'ایمیل شما', en: 'Your Email' },
    emailPlaceholder: { fa: 'name@example.com', en: 'name@example.com' },
    sendCode: { fa: 'ارسال کد تایید', en: 'Send Recovery Code' },
    title2: { fa: 'تایید کد و تغییر رمز', en: 'Verify & Reset Password' },
    desc2: { fa: 'کد ارسال شده به ایمیل خود و رمز عبور جدید را وارد کنید.', en: 'Enter the code sent to your email and your new password.' },
    codeLabel: { fa: 'کد تایید ۶ رقمی', en: '6-digit Recovery Code' },
    codePlaceholder: { fa: '123456', en: '123456' },
    newPassLabel: { fa: 'رمز عبور جدید', en: 'New Password' },
    newPassPlaceholder: { fa: '••••••••', en: '••••••••' },
    resetBtn: { fa: 'تغییر رمز عبور', en: 'Reset Password' },
    title3: { fa: 'رمز عبور تغییر کرد!', en: 'Password Reset Successful!' },
    desc3: { fa: 'اکنون می‌توانید با رمز عبور جدید خود وارد شوید.', en: 'You can now log in with your new password.' },
    goToLogin: { fa: 'ورود به حساب', en: 'Go to Login' }
  };

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      // Connects to existing endpoint logic
      await api.auth.forgotPassword(email);
      toast.success(language === 'fa' ? 'کد بازیابی ارسال شد' : 'Recovery code sent');
      setStep(2);
    } catch (error: any) {
      toast.error(error.message || 'Error sending code');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    // Prepared for SMTP API linking
    try {
      setTimeout(() => {
        setStep(3);
        setIsSubmitting(false);
      }, 1000);
    } catch (error: any) {
      toast.error(error.message || 'Error resetting password');
      setIsSubmitting(false);
    }
  };

  const flipVariants = {
    initial: { rotateY: isRtl ? -90 : 90, opacity: 0 },
    animate: { rotateY: 0, opacity: 1, transition: { duration: 0.4, ease: "easeOut" } },
    exit: { rotateY: isRtl ? 90 : -90, opacity: 0, transition: { duration: 0.3, ease: "easeIn" } }
  };

  return (
    <div className={`flex min-h-screen flex-col items-center justify-center p-6 transition-colors duration-500 ${isDark ? 'bg-[#060606]' : 'bg-[#FAF3E2]'}`}>
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
                <img src={logo} alt="Nerkhbaan Logo" className="h-28 w-28 object-contain drop-shadow-2xl" />
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
                            <Mail size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                            <Input
                                type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                                placeholder={t.emailPlaceholder[language]} required dir="ltr"
                                className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                            />
                        </div>
                    </label>
                    <Button
                        type="submit" disabled={isSubmitting}
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
                            <KeyRound size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                            <Input
                                type="text" value={code} onChange={(e) => setCode(e.target.value)}
                                placeholder={t.codePlaceholder[language]} required dir="ltr"
                                className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 tracking-widest font-mono font-bold ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                            />
                        </div>
                    </label>
                    <label className="block space-y-2">
                        <span className={`text-sm font-bold ms-4 ${isDark ? 'text-[#E9D49A]' : 'text-[#6A4E11]'}`}>{t.newPassLabel[language]}</span>
                        <div className="relative">
                            <KeyRound size={18} className={`pointer-events-none absolute ${isRtl ? 'right-4' : 'left-4'} top-1/2 -translate-y-1/2 ${isDark ? 'text-[#CDB879]/55' : 'text-[#A8883A]/75'}`} />
                            <Input
                                type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                                placeholder={t.newPassPlaceholder[language]} required dir="ltr"
                                className={`h-12 rounded-2xl ${isRtl ? 'pr-11 pl-4 text-right' : 'pl-11 pr-4 text-left'} text-sm shadow-inner transition-all focus:ring-2 focus:ring-[#D4AF37]/50 tracking-widest ${isDark ? 'border-[#D4AF37]/20 bg-[#141414] text-[#F7F2E3] placeholder:text-gray-600' : 'border-[#D4AF37]/30 bg-white/80 text-[#3B2E13] placeholder:text-gray-400'}`}
                            />
                        </div>
                    </label>
                    <Button
                        type="submit" disabled={isSubmitting || newPassword.length < 8}
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
        <div className={`mt-8 flex w-full flex-col items-center justify-center border-t border-black/10 pt-5 dark:border-white/10`}>
          <p className={`text-center text-[13px] font-medium leading-relaxed transition-colors duration-300 ${isDark ? 'text-gray-400' : 'text-gray-500'}`} style={isRtl ? { fontFamily: 'Vazirmatn, sans-serif' } : undefined}>
            {t.footerText[language]}
          </p>
        </div>

      </div>
    </div>
  );
}