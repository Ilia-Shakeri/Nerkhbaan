import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import logo from '../../logo/logo.png';

interface SplashScreenProps {
  onComplete: () => void;
  language: 'fa' | 'en';
  theme: 'dark' | 'light';
}

const TICKERS = [
  { symbol: 'BTC',  price: '67,842', change: '+2.4%', up: true },
  { symbol: 'XAU',  price: '2,331',  change: '-0.3%', up: false },
  { symbol: 'ETH',  price: '3,521',  change: '+1.8%', up: true },
  { symbol: 'USD',  price: '58,200', change: '+0.6%', up: true },
  { symbol: 'USDT', price: '58,150', change: '+0.5%', up: true },
  { symbol: 'EUR',  price: '63,400', change: '+0.2%', up: true },
];

const PARTICLES = Array.from({ length: 22 }, (_, i) => ({
  id: i,
  x: 5 + (i * 4.3) % 90,
  y: 10 + (i * 7.1) % 80,
  size: 1.5 + (i % 4) * 0.8,
  delay: (i * 0.37) % 2.8,
  duration: 4 + (i % 5),
}));

export function SplashScreen({ onComplete, language, theme }: SplashScreenProps) {
  const isDark = theme === 'dark';
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const step = 100 / 30;
    const interval = setInterval(() => {
      setProgress(p => Math.min(p + step, 100));
    }, 100);
    const timer = setTimeout(onComplete, 3200);
    return () => { clearInterval(interval); clearTimeout(timer); };
  }, [onComplete]);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0, transition: { duration: 0.55, ease: 'easeInOut' } }}
        className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden"
        style={{
          background: isDark
            ? 'radial-gradient(ellipse at 55% 45%, #181208 0%, #0A0A0A 55%, #050505 100%)'
            : 'radial-gradient(ellipse at 55% 45%, #FFF8E8 0%, #FFF3D8 60%, #FAF0D0 100%)',
        }}
      >
        {/* Subtle grid */}
        <div
          className="pointer-events-none absolute inset-0 opacity-100"
          style={{
            backgroundImage: isDark
              ? 'linear-gradient(rgba(212,175,55,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(212,175,55,0.035) 1px, transparent 1px)'
              : 'linear-gradient(rgba(212,175,55,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(212,175,55,0.07) 1px, transparent 1px)',
            backgroundSize: '52px 52px',
          }}
        />

        {/* Central ambient glow */}
        <motion.div
          className="pointer-events-none absolute rounded-full"
          style={{
            width: 560, height: 560,
            left: '50%', top: '50%',
            transform: 'translate(-50%, -50%)',
            background: isDark
              ? 'radial-gradient(circle, rgba(212,175,55,0.10) 0%, transparent 68%)'
              : 'radial-gradient(circle, rgba(212,175,55,0.16) 0%, transparent 68%)',
          }}
          animate={{ scale: [1, 1.14, 1], opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 3.5, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* Secondary floating orb top-right */}
        <motion.div
          className="pointer-events-none absolute rounded-full"
          style={{
            width: 220, height: 220,
            right: '12%', top: '18%',
            background: isDark
              ? 'radial-gradient(circle, rgba(212,175,55,0.06) 0%, transparent 70%)'
              : 'radial-gradient(circle, rgba(212,175,55,0.10) 0%, transparent 70%)',
          }}
          animate={{ x: [0, 18, 0], y: [0, -14, 0], scale: [1, 1.2, 1] }}
          transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* Secondary floating orb bottom-left */}
        <motion.div
          className="pointer-events-none absolute rounded-full"
          style={{
            width: 180, height: 180,
            left: '8%', bottom: '22%',
            background: isDark
              ? 'radial-gradient(circle, rgba(212,175,55,0.05) 0%, transparent 70%)'
              : 'radial-gradient(circle, rgba(212,175,55,0.09) 0%, transparent 70%)',
          }}
          animate={{ x: [0, -12, 0], y: [0, 16, 0], scale: [1, 1.15, 1] }}
          transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut', delay: 1 }}
        />

        {/* Floating particles */}
        {PARTICLES.map(p => (
          <motion.div
            key={p.id}
            className="pointer-events-none absolute rounded-full"
            style={{
              left: `${p.x}%`,
              top: `${p.y}%`,
              width: p.size,
              height: p.size,
              background: isDark ? 'rgba(212,175,55,0.55)' : 'rgba(160,120,40,0.45)',
            }}
            animate={{ y: [0, -55], opacity: [0, 0.85, 0] }}
            transition={{
              delay: p.delay,
              duration: p.duration,
              repeat: Infinity,
              ease: 'easeOut',
            }}
          />
        ))}

        {/* Main content column */}
        <div className="relative flex flex-col items-center">

          {/* Logo with pulse rings */}
          <div className="relative flex items-center justify-center">
            <motion.div
              className="absolute rounded-full border"
              style={{
                width: 188, height: 188,
                borderColor: isDark ? 'rgba(212,175,55,0.22)' : 'rgba(180,140,40,0.28)',
              }}
              animate={{ scale: [1, 1.55], opacity: [0.65, 0] }}
              transition={{ duration: 2.2, repeat: Infinity, ease: 'easeOut' }}
            />
            <motion.div
              className="absolute rounded-full border"
              style={{
                width: 188, height: 188,
                borderColor: isDark ? 'rgba(212,175,55,0.14)' : 'rgba(180,140,40,0.18)',
              }}
              animate={{ scale: [1, 1.55], opacity: [0.45, 0] }}
              transition={{ duration: 2.2, delay: 0.55, repeat: Infinity, ease: 'easeOut' }}
            />
            <motion.div
              className="absolute rounded-full"
              style={{
                width: 144, height: 144,
                background: isDark
                  ? 'radial-gradient(circle, rgba(212,175,55,0.08) 0%, transparent 70%)'
                  : 'radial-gradient(circle, rgba(212,175,55,0.12) 0%, transparent 70%)',
              }}
              animate={{ scale: [1, 1.1, 1] }}
              transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
            />
            <motion.img
              src={logo}
              alt="Nerkhbaan"
              className="relative z-10 h-36 w-36 object-contain"
              style={{ filter: 'drop-shadow(0 8px 32px rgba(212,175,55,0.35))' }}
              initial={{ scale: 0.55, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>

          {/* Brand name */}
          <motion.h1
            initial={{ y: 22, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.38, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
            className="mt-3 select-none"
            style={{
              fontSize: language === 'fa' ? '3rem' : '2.75rem',
              fontWeight: language === 'fa' ? 400 : 900,
              lineHeight: language === 'fa' ? 2.2 : 1.15,
              letterSpacing: language === 'fa' ? 'normal' : '-0.02em',
              direction: language === 'fa' ? 'rtl' : 'ltr',
              fontFamily: language === 'fa' ? '"Noto Nastaliq Urdu", "Vazirmatn", serif' : undefined,
              background: isDark
                ? 'linear-gradient(135deg, #C8A228 0%, #F3E2AB 45%, #D4AF37 100%)'
                : 'linear-gradient(135deg, #3B2E13 0%, #8A6A23 50%, #3B2E13 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            {language === 'fa' ? 'نرخ‌بان' : 'Nerkhbaan'}
          </motion.h1>

          {/* Tagline */}
          <motion.p
            initial={{ y: 14, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.62, duration: 0.5 }}
            className="mt-1.5 select-none text-xs font-semibold tracking-[0.18em] uppercase"
            style={{ color: isDark ? 'rgba(212,175,55,0.55)' : 'rgba(100,70,10,0.55)' }}
          >
            {language === 'fa' ? 'پلتفرم هوشمند ردیابی قیمت' : 'Smart Price Intelligence'}
          </motion.p>

          {/* Ticker strip */}
          <motion.div
            initial={{ opacity: 0, y: 18, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ delay: 0.85, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="relative mt-9 w-72 overflow-hidden rounded-2xl"
            style={{
              border: isDark ? '1px solid rgba(212,175,55,0.15)' : '1px solid rgba(212,175,55,0.22)',
              background: isDark ? 'rgba(12,10,5,0.82)' : 'rgba(255,252,240,0.72)',
              backdropFilter: 'blur(10px)',
              padding: '8px 0',
            }}
          >
            {/* Fade masks left/right */}
            <div
              className="pointer-events-none absolute inset-y-0 left-0 z-10 w-8"
              style={{ background: isDark ? 'linear-gradient(to right, rgba(12,10,5,0.9), transparent)' : 'linear-gradient(to right, rgba(255,252,240,0.9), transparent)' }}
            />
            <div
              className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8"
              style={{ background: isDark ? 'linear-gradient(to left, rgba(12,10,5,0.9), transparent)' : 'linear-gradient(to left, rgba(255,252,240,0.9), transparent)' }}
            />
            <motion.div
              className="flex gap-7 px-4"
              animate={{ x: ['0%', '-50%'] }}
              transition={{ duration: 14, repeat: Infinity, ease: 'linear' }}
            >
              {[...TICKERS, ...TICKERS].map((t, i) => (
                <div key={i} className="flex shrink-0 items-center gap-2">
                  <span
                    className="text-[11px] font-bold"
                    style={{ color: isDark ? 'rgba(243,226,171,0.9)' : 'rgba(58,40,8,0.85)' }}
                  >
                    {t.symbol}
                  </span>
                  <span
                    className="font-mono text-[11px]"
                    style={{ color: isDark ? '#D4AF37' : '#7A5C10' }}
                  >
                    {t.price}
                  </span>
                  <span
                    className="text-[10px] font-bold"
                    style={{ color: t.up ? '#10b981' : '#f87171' }}
                  >
                    {t.change}
                  </span>
                </div>
              ))}
            </motion.div>
          </motion.div>

          {/* Chart */}
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1.05, duration: 0.5 }}
            className="relative mt-5 h-16 w-72"
          >
            <svg width="288" height="64" viewBox="0 0 288 64" className="absolute inset-0">
              <defs>
                <linearGradient id="splashLineGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%"   stopColor={isDark ? '#D4AF37' : '#8A6A23'} stopOpacity="0.5" />
                  <stop offset="45%"  stopColor={isDark ? '#F3E2AB' : '#D4AF37'} stopOpacity="1" />
                  <stop offset="100%" stopColor={isDark ? '#D4AF37' : '#8A6A23'} stopOpacity="0.5" />
                </linearGradient>
                <linearGradient id="splashAreaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor={isDark ? '#D4AF37' : '#C9A227'} stopOpacity="0.22" />
                  <stop offset="100%" stopColor={isDark ? '#D4AF37' : '#C9A227'} stopOpacity="0" />
                </linearGradient>
              </defs>
              {/* Area fill */}
              <motion.path
                d="M 0,50 C 18,48 28,42 44,38 C 60,34 66,40 82,32 C 98,24 104,28 120,20 C 136,12 144,18 160,26 C 176,34 184,28 200,20 C 216,12 226,16 244,10 C 262,4 272,8 288,4 L 288,64 L 0,64 Z"
                fill="url(#splashAreaGrad)"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 1.25, duration: 0.8 }}
              />
              {/* Line */}
              <motion.path
                d="M 0,50 C 18,48 28,42 44,38 C 60,34 66,40 82,32 C 98,24 104,28 120,20 C 136,12 144,18 160,26 C 176,34 184,28 200,20 C 216,12 226,16 244,10 C 262,4 272,8 288,4"
                fill="none"
                stroke="url(#splashLineGrad)"
                strokeWidth="2.5"
                strokeLinecap="round"
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ delay: 1.15, duration: 1.4, ease: 'easeInOut' }}
              />
              {/* Trailing dot */}
              <motion.circle
                r="4"
                fill={isDark ? '#F3E2AB' : '#C9A227'}
                style={{ filter: 'drop-shadow(0 0 5px rgba(212,175,55,0.8))' }}
                initial={{ opacity: 0 }}
                animate={{ cx: [0, 288], cy: [50, 4], opacity: [0, 1, 1, 0] }}
                transition={{ delay: 1.15, duration: 1.4, ease: 'easeInOut' }}
              />
            </svg>
          </motion.div>

          {/* Progress bar */}
          <motion.div
            initial={{ opacity: 0, scaleX: 0 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{ delay: 0.45, duration: 0.4 }}
            className="mt-6 h-px w-44 overflow-hidden rounded-full"
            style={{ background: isDark ? 'rgba(212,175,55,0.12)' : 'rgba(212,175,55,0.18)' }}
          >
            <motion.div
              className="h-full rounded-full"
              style={{
                background: 'linear-gradient(to right, #D4AF37, #F3E2AB)',
                width: `${progress}%`,
                boxShadow: '0 0 8px rgba(212,175,55,0.6)',
              }}
            />
          </motion.div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
