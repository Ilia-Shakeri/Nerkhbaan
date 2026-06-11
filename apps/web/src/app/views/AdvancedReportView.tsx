import React, { useEffect, useRef } from 'react';
import { useAppContext } from '../context/AppContext';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { TrendingUp, AlertCircle } from 'lucide-react';

export function AdvancedReportView() {
  const { language, theme } = useAppContext();
  const containerRef = useRef<HTMLDivElement>(null);
  const isDark = theme === 'dark';

  const t = {
    title: { fa: 'گزارش پیشرفته', en: 'Advanced Report' },
    subtitle: { fa: 'تحلیل تکنیکال و اسکن بازار', en: 'Technical Analysis & Market Scanning' },
    loading: { fa: 'در حال بارگذاری نمودار...', en: 'Loading chart...' },
  };

  useEffect(() => {
    if (!containerRef.current) return;

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/tv.js';
    script.async = true;
    script.onload = () => {
      if (typeof (window as any).TradingView !== 'undefined') {
        new (window as any).TradingView.widget({
          autosize: true,
          symbol: 'BINANCE:BTCUSDT',
          interval: 'D',
          timezone: 'Asia/Tehran',
          theme: isDark ? 'dark' : 'light',
          style: '1',
          locale: language === 'fa' ? 'en' : 'en',
          toolbar_bg: isDark ? '#0E0E0E' : '#FFFFFF',
          enable_publishing: false,
          allow_symbol_change: true,
          container_id: 'tradingview_widget',
          studies: [
            'RSI@tv-basicstudies',
            'MASimple@tv-basicstudies',
            'MACD@tv-basicstudies'
          ],
          supported_resolutions: ['1', '5', '15', '60', 'D', 'W', 'M'],
        });
      }
    };
    document.head.appendChild(script);

    return () => {
      if (script.parentNode) {
        script.parentNode.removeChild(script);
      }
    };
  }, [isDark, language]);

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#D4AF37]/10">
          <TrendingUp className="text-[#D4AF37]" size={24} />
        </div>
        <div>
          <h1 className={`text-2xl font-bold ${isDark ? 'text-white' : 'text-[#0B1F3A]'}`}>
            {t.title[language]}
          </h1>
          <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            {t.subtitle[language]}
          </p>
        </div>
      </div>

      <Card className="p-0 overflow-hidden">
        <div ref={containerRef} className="relative" style={{ height: '80vh', minHeight: '600px' }}>
          <div id="tradingview_widget" className="h-full w-full"></div>
          <div className={`absolute inset-0 flex items-center justify-center pointer-events-none ${isDark ? 'bg-[#0E0E0E]/80' : 'bg-white/80'}`}>
            <div className="flex items-center gap-2">
              <AlertCircle className={isDark ? 'text-gray-400' : 'text-gray-600'} size={18} />
              <span className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                {t.loading[language]}
              </span>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
