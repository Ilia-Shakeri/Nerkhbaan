import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import logo from '../../logo/logo.png';

interface SplashScreenProps {
  onComplete: () => void;
  language: 'fa' | 'en';
  theme: 'dark' | 'light';
}

export function SplashScreen({ onComplete, language, theme }: SplashScreenProps) {
  const isDark = theme === 'dark';

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Nerkhbaan' },
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      onComplete();
    }, 3000);
    
    return () => clearInterval(timer);
  }, [onComplete]);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className={`fixed inset-0 z-50 flex items-center justify-center overflow-hidden ${
          isDark 
            ? 'bg-gradient-to-br from-[#0A0A0A] via-[#141414] to-[#0E0E0E]' 
            : 'bg-gradient-to-br from-[#FFF8E8] via-[#FFFCF2] to-[#FFF5DC]'
        }`}
        style={{ width: '100vw', height: '100vh' }}
      >
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="flex flex-col items-center"
        >
          <motion.img
            src={logo}
            alt="Logo"
            className="h-40 w-40 object-contain"
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

          <motion.h1
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.3 }}
            className={`mt-20 text-5xl font-bold ${
              isDark 
                ? 'bg-gradient-to-r from-[#D4AF37] via-[#F3E2AB] to-[#D4AF37] bg-clip-text text-transparent' 
                : 'bg-gradient-to-r from-[#3B2E13] via-[#8A6A23] to-[#3B2E13] bg-clip-text text-transparent'
            }`}
            style={{ 
              fontFamily: '"Noto Nastaliq Urdu", "Vazirmatn", serif',
              direction: 'rtl',
              letterSpacing: 'normal',
              lineHeight: '2.2',
              unicodeBidi: 'embed',
              textRendering: 'optimizeLegibility',
              WebkitFontSmoothing: 'antialiased'
            }}
          >
            {t.brandName[language]}
          </motion.h1>

          <motion.div
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.7 }}
            className="relative mt-16 h-32 w-96"
          >
            <svg
              width="384"
              height="128"
              viewBox="0 0 384 128"
              className="absolute inset-0"
            >
              <defs>
                <linearGradient id="chartGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor={isDark ? '#D4AF37' : '#8A6A23'} stopOpacity="0.8" />
                  <stop offset="50%" stopColor={isDark ? '#F3E2AB' : '#D4AF37'} stopOpacity="1" />
                  <stop offset="100%" stopColor={isDark ? '#D4AF37' : '#8A6A23'} stopOpacity="0.8" />
                </linearGradient>
              </defs>
              
              <motion.path
                d="M 0,80 L 12,75 L 24,68 L 36,72 L 48,65 L 60,58 L 72,62 L 84,55 L 96,48 L 108,52 L 120,45 L 132,50 L 144,42 L 156,48 L 168,38 L 180,44 L 192,50 L 204,55 L 216,48 L 228,52 L 240,45 L 252,50 L 264,42 L 276,48 L 288,40 L 300,45 L 312,38 L 324,42 L 336,35 L 348,40 L 360,32 L 372,35 L 384,28"
                fill="none"
                stroke="url(#chartGradient)"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{ 
                  pathLength: [0, 1],
                  opacity: [0, 1]
                }}
                transition={{
                  pathLength: {
                    duration: 3,
                    ease: 'linear'
                  },
                  opacity: {
                    duration: 0.5,
                    ease: 'easeIn'
                  }
                }}
              />
              
              <motion.circle
                cx="0"
                cy="0"
                r="4"
                fill={isDark ? '#F3E2AB' : '#D4AF37'}
                initial={{ opacity: 0 }}
                animate={{ 
                  cx: [0, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120, 132, 144, 156, 168, 180, 192, 204, 216, 228, 240, 252, 264, 276, 288, 300, 312, 324, 336, 348, 360, 372, 384],
                  cy: [80, 75, 68, 72, 65, 58, 62, 55, 48, 52, 45, 50, 42, 48, 38, 44, 50, 55, 48, 52, 45, 50, 42, 48, 40, 45, 38, 42, 35, 40, 32, 35, 28],
                  opacity: [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
                }}
                transition={{
                  duration: 3,
                  ease: 'linear'
                }}
              />
            </svg>
          </motion.div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
