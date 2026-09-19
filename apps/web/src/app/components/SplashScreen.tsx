import React, { useEffect } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import logo from '../../logo/logo.png';

interface SplashScreenProps {
  onComplete: () => void;
  language: 'fa' | 'en';
  theme: 'dark' | 'light';
}

const PARTICLES = Array.from({ length: 12 }, (_, index) => ({
  id: index,
  x: 8 + (index * 7.9) % 84,
  y: 12 + (index * 11.3) % 76,
  size: 2 + (index % 3),
  delay: (index * 0.17) % 1.2,
}));

const APP_VERSION = 'v2.7.0';

export function SplashScreen({ onComplete, language, theme }: SplashScreenProps) {
  const isDark = theme === 'dark';

  useEffect(() => {
    const timer = window.setTimeout(onComplete, 420);
    return () => window.clearTimeout(timer);
  }, [onComplete]);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0, scale: 0.985 }}
        transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
        className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden"
        style={{
          background: isDark
            ? 'radial-gradient(ellipse at 55% 45%, #181208 0%, #0A0A0A 55%, #050505 100%)'
            : 'radial-gradient(ellipse at 55% 45%, #FFF8E8 0%, #FFF3D8 60%, #FAF0D0 100%)',
        }}
      >
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage: isDark
              ? 'linear-gradient(rgba(212,175,55,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(212,175,55,0.035) 1px, transparent 1px)'
              : 'linear-gradient(rgba(212,175,55,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(212,175,55,0.07) 1px, transparent 1px)',
            backgroundSize: '52px 52px',
          }}
        />

        {PARTICLES.map((particle) => (
          <motion.span
            key={particle.id}
            className="pointer-events-none absolute rounded-full bg-[#D4AF37]"
            style={{
              left: `${particle.x}%`,
              top: `${particle.y}%`,
              width: particle.size,
              height: particle.size,
            }}
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: [0.08, 0.42, 0.08], scale: [0.8, 1.1, 0.8] }}
            transition={{ duration: 2.8, delay: particle.delay, repeat: Infinity, ease: 'easeInOut' }}
          />
        ))}

        <div className="relative z-10 flex flex-col items-center px-6 text-center">
          <motion.img
            src={logo}
            alt="Nerkhbaan"
            className="h-32 w-32 object-contain"
            style={{ filter: 'drop-shadow(0 8px 28px rgba(212,175,55,0.34))' }}
            initial={{ scale: 0.72, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', bounce: 0, duration: 0.36 }}
          />

          <motion.h1
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.08, duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="mt-1 select-none"
            style={{
              fontSize: language === 'fa' ? '3rem' : '2.75rem',
              fontWeight: language === 'fa' ? 400 : 900,
              lineHeight: language === 'fa' ? 2 : 1.1,
              letterSpacing: language === 'fa' ? 'normal' : '-0.02em',
              direction: language === 'fa' ? 'rtl' : 'ltr',
              fontFamily: language === 'fa'
                ? '"Noto Nastaliq Urdu", "Vazirmatn", serif'
                : 'Inter, system-ui, sans-serif',
              background: isDark
                ? 'linear-gradient(135deg, #C8A228 0%, #F3E2AB 45%, #D4AF37 100%)'
                : 'linear-gradient(135deg, #3B2E13 0%, #8A6A23 50%, #3B2E13 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            {language === 'fa' ? 'نرخ‌بان' : 'Nerkhbaan'}
          </motion.h1>

          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.16, duration: 0.22 }}
            className="mt-4 flex min-h-11 items-center gap-3 rounded-2xl border px-5 py-2 text-xs font-semibold backdrop-blur-md"
            style={{
              borderColor: isDark ? 'rgba(212,175,55,0.18)' : 'rgba(138,106,35,0.24)',
              color: isDark ? '#E8D9AE' : '#5E4714',
              background: isDark ? 'rgba(12,10,5,0.82)' : 'rgba(255,252,240,0.82)',
            }}
            role="status"
            aria-live="polite"
          >
            <span className="h-2 w-2 animate-pulse rounded-full bg-[#D4AF37]" />
            <span>{language === 'fa' ? 'در حال آماده‌سازی برنامه' : 'Preparing the application'}</span>
          </motion.div>

          <span className="mt-3 select-none font-mono text-xs" style={{ color: isDark ? 'rgba(212,175,55,0.48)' : 'rgba(100,70,10,0.55)' }}>
            {APP_VERSION}
          </span>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
