import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { TrendingUp } from 'lucide-react';
import logo from '../../logo/logo.png';

interface SplashScreenProps {
  onComplete: () => void;
  language: 'fa' | 'en';
  theme: 'dark' | 'light';
}

export function SplashScreen({ onComplete, language, theme }: SplashScreenProps) {
  const [progress, setProgress] = useState(0);
  const isDark = theme === 'dark';

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Nerkhbaan' },
    tagline: { fa: 'ردیابی و هشدار هوشمند قیمت', en: 'Smart Price Tracking' },
  };

  useEffect(() => {
    const duration = 2500;
    const steps = 50;
    const interval = duration / steps;

    let currentStep = 0;
    const timer = setInterval(() => {
      currentStep += 1;
      const newProgress = (currentStep / steps) * 100;
      setProgress(newProgress);

      if (currentStep >= steps) {
        clearInterval(timer);
        setTimeout(onComplete, 300);
      }
    }, interval);

    return () => clearInterval(timer);
  }, [onComplete]);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className={`fixed inset-0 z-50 flex flex-col items-center justify-center ${
          isDark 
            ? 'bg-gradient-to-br from-[#0A0A0A] via-[#141414] to-[#0E0E0E]' 
            : 'bg-gradient-to-br from-[#FFF8E8] via-[#FFFCF2] to-[#FFF5DC]'
        }`}
      >
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="flex flex-col items-center gap-8"
        >
          <motion.img
            src={logo}
            alt="Logo"
            className="h-24 w-24 object-contain"
            animate={{ 
              rotate: [0, 5, -5, 0],
              scale: [1, 1.05, 1]
            }}
            transition={{ 
              duration: 2,
              repeat: Infinity,
              ease: 'easeInOut'
            }}
          />

          <div className="flex flex-col items-center gap-3">
            <motion.h1
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.3 }}
              className={`text-5xl font-black tracking-tight ${
                isDark 
                  ? 'bg-gradient-to-r from-[#D4AF37] via-[#F3E2AB] to-[#D4AF37] bg-clip-text text-transparent' 
                  : 'bg-gradient-to-r from-[#3B2E13] via-[#8A6A23] to-[#3B2E13] bg-clip-text text-transparent'
              }`}
              style={{ fontFamily: 'Vazirmatn, sans-serif' }}
            >
              {t.brandName[language]}
            </motion.h1>

            <motion.p
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.5 }}
              className={`text-sm font-medium ${isDark ? 'text-[#CDB879]' : 'text-[#8A6A23]'}`}
              style={{ fontFamily: 'Vazirmatn, sans-serif' }}
            >
              {t.tagline[language]}
            </motion.p>
          </div>

          <motion.div
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.7 }}
            className="relative mt-8 h-2 w-64 overflow-hidden rounded-full bg-white/10"
          >
            <motion.div
              className={`h-full rounded-full ${
                isDark 
                  ? 'bg-gradient-to-r from-[#D4AF37] to-[#F3E2AB]' 
                  : 'bg-gradient-to-r from-[#8A6A23] to-[#D4AF37]'
              }`}
              style={{ width: `${progress}%` }}
              initial={{ width: '0%' }}
              animate={{ width: `${progress}%` }}
              transition={{ ease: 'easeOut' }}
            />
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1, duration: 1 }}
            className="mt-4 flex items-center gap-2"
          >
            <TrendingUp 
              className={`${isDark ? 'text-[#D4AF37]' : 'text-[#8A6A23]'}`} 
              size={20}
            />
            <motion.span
              className={`text-xs font-medium ${isDark ? 'text-gray-400' : 'text-gray-600'}`}
              animate={{ opacity: [0.5, 1, 0.5] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              {language === 'fa' ? 'در حال بارگذاری...' : 'Loading...'}
            </motion.span>
          </motion.div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
