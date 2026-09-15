import React, { useEffect, useRef, useState } from 'react';
import { useAppContext } from '../context/AppContext';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { TrendingUp, AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';

export function AdvancedReportView() {
  const { language, theme } = useAppContext();
  const containerRef = useRef<HTMLDivElement>(null);
  const isDark = theme === 'dark';
  
  const [chartState, setChartState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [retryKey, setRetryKey] = useState(0);

  const t = {
    title: { fa: 'گزارش پیشرفته', en: 'Advanced Report' },
    subtitle: { fa: 'تحلیل تکنیکال و اسکن بازار', en: 'Technical Analysis & Market Scanning' },
    loading: { fa: 'در حال بارگذاری نمودار...', en: 'Loading chart...' },
    loadError: { fa: 'نمودار بیرونی بارگذاری نشد.', en: 'The external chart could not be loaded.' },
    retry: { fa: 'تلاش دوباره', en: 'Try again' },
  };

  useEffect(() => {
    if (!containerRef.current) return;

    let active = true;
    let script = document.getElementById('market-chart-script') as HTMLScriptElement | null;
    let timeout = 0;
    setChartState('loading');

    const initializeChart = () => {
      if (!active) return;
      if (typeof (window as any).TradingView !== 'undefined') {
        containerRef.current?.replaceChildren();
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
        setChartState('ready');
      } else {
        setChartState('error');
      }
    };
    const failChart = () => {
      if (!active) return;
      if (script) script.dataset.failed = 'true';
      setChartState('error');
    };

    if (typeof (window as any).TradingView !== 'undefined') {
      initializeChart();
    } else {
      if (script?.dataset.failed === 'true') {
        script.remove();
        script = null;
      }
      if (!script) {
        script = document.createElement('script');
        script.id = 'market-chart-script';
        script.src = 'https://s3.tradingview.com/tv.js';
        script.async = true;
        document.head.appendChild(script);
      }
      script.addEventListener('load', initializeChart, { once: true });
      script.addEventListener('error', failChart, { once: true });
      timeout = window.setTimeout(failChart, 12_000);
    }

    return () => {
      active = false;
      window.clearTimeout(timeout);
      script?.removeEventListener('load', initializeChart);
      script?.removeEventListener('error', failChart);
      containerRef.current?.replaceChildren();
    };
  }, [isDark, retryKey]);

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
        <div className="relative h-[65dvh] min-h-[420px] sm:min-h-[600px]">
          <div ref={containerRef} id="tradingview_widget" className="h-full w-full" />
          
          {/* Conditionally render the loading overlay */}
          {chartState !== 'ready' && (
            <div className={`absolute inset-0 flex items-center justify-center ${isDark ? 'bg-[#0E0E0E]/95' : 'bg-white/95'}`} role="status">
              <div className="flex max-w-sm flex-col items-center gap-3 px-6 text-center">
                {chartState === 'loading' ? (
                  <Loader2 className="animate-spin text-[#D4AF37]" size={24} />
                ) : (
                  <AlertCircle className="text-amber-500" size={24} />
                )}
                <span className={`text-sm ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
                  {chartState === 'loading' ? t.loading[language] : t.loadError[language]}
                </span>
                {chartState === 'error' && (
                  <Button type="button" onClick={() => setRetryKey((value) => value + 1)} className="gap-2 bg-[#D4AF37] text-black">
                    <RefreshCw size={16} />
                    {t.retry[language]}
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
