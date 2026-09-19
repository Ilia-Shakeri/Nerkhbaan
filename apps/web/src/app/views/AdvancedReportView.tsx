import { useEffect, useRef, useState } from 'react';
import { ExternalLink, LoaderCircle, ShieldCheck } from 'lucide-react';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { useAppContext } from '../context/AppContext';

export function AdvancedReportView() {
  const { language, theme } = useAppContext();
  const containerRef = useRef<HTMLDivElement>(null);
  const [allowed, setAllowed] = useState(false);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const isDark = theme === 'dark';

  useEffect(() => {
    if (!allowed || !containerRef.current) return;
    const container = containerRef.current;
    container.replaceChildren();
    setStatus('loading');
    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget h-full w-full';
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.text = JSON.stringify({
      autosize: true,
      symbol: 'BINANCE:BTCUSDT',
      interval: '60',
      timezone: 'Asia/Tehran',
      theme: isDark ? 'dark' : 'light',
      style: '1',
      locale: language === 'fa' ? 'fa_IR' : 'en',
      allow_symbol_change: true,
      calendar: false,
      hide_side_toolbar: false,
      withdateranges: true,
      support_host: 'https://www.tradingview.com',
    });
    script.onload = () => setStatus('ready');
    script.onerror = () => setStatus('error');
    container.append(widget, script);
    return () => container.replaceChildren();
  }, [allowed, isDark, language]);

  return (
    <section className="mx-auto max-w-7xl space-y-5">
      <div className={`rounded-3xl border p-5 sm:p-7 ${isDark ? 'border-[#D4AF37]/20 bg-[#0E0E0E] text-[#E8D9AE]' : 'border-[#D4AF37]/25 bg-white/75 text-[#3B2E13]'}`}>
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div>
            <h1 className="text-2xl font-black sm:text-3xl">{language === 'fa' ? 'نمودار پیشرفته TradingView' : 'Advanced TradingView chart'}</h1>
            <p className={`mt-2 max-w-3xl text-sm leading-7 ${isDark ? 'text-[#CDBB8C]' : 'text-[#6E5317]'}`}>
              {language === 'fa' ? 'این نمودار فقط با انتخاب شما بار می‌شود. با بارگذاری، نشانی شبکه و مشخصات مرورگر برای TradingView فرستاده می‌شود و کوکی‌های آن تابع سیاست همان سرویس است.' : 'This chart loads only after your choice. Loading sends network and browser details to TradingView, whose own cookie and privacy terms apply.'}
            </p>
          </div>
          <Button asChild variant="outline"><a href="https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT" target="_blank" rel="noopener noreferrer"><ExternalLink size={17} />{language === 'fa' ? 'باز کردن در برگه جدید' : 'Open in new tab'}</a></Button>
        </div>
      </div>

      {!allowed ? (
        <div className={`flex min-h-[520px] flex-col items-center justify-center rounded-3xl border p-6 text-center ${isDark ? 'border-white/10 bg-[#0B0B0B]' : 'border-[#D4AF37]/20 bg-[#FFF3D8]'}`}>
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#D4AF37] text-[#171006]"><ShieldCheck size={27} /></div>
          <h2 className="text-lg font-bold">{language === 'fa' ? 'بارگذاری با اجازه شما' : 'Load with your permission'}</h2>
          <p className={`mt-2 max-w-lg text-sm leading-7 ${isDark ? 'text-[#CDBB8C]' : 'text-[#6E5317]'}`}>{language === 'fa' ? 'تا پیش از زدن دکمه، هیچ فایل یا محتوایی از TradingView دریافت نمی‌شود.' : 'No TradingView file or content is requested until you press the button.'}</p>
          <Button type="button" variant="primary" className="mt-5" onClick={() => setAllowed(true)}>{language === 'fa' ? 'بارگذاری نمودار TradingView' : 'Load TradingView chart'}</Button>
        </div>
      ) : (
        <div className={`relative h-[620px] min-h-[520px] overflow-hidden rounded-3xl border ${isDark ? 'border-white/10 bg-[#0B0B0B]' : 'border-[#D4AF37]/20 bg-white'}`}>
          {status === 'loading' && <div className="absolute inset-0 z-10 flex items-center justify-center gap-2"><LoaderCircle className="animate-spin" /><span>{language === 'fa' ? 'در حال بارگذاری نمودار…' : 'Loading chart…'}</span></div>}
          {status === 'error' && <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 p-6 text-center"><p>{language === 'fa' ? 'نمودار بار نشد. اتصال یا محدودیت شبکه را بررسی کنید.' : 'The chart did not load. Check network access or filtering.'}</p><Button type="button" variant="outline" onClick={() => { setAllowed(false); setStatus('idle'); }}>{language === 'fa' ? 'تلاش دوباره' : 'Try again'}</Button></div>}
          <div ref={containerRef} className="h-full w-full" aria-label={language === 'fa' ? 'نمودار تعاملی TradingView' : 'Interactive TradingView chart'} />
        </div>
      )}
    </section>
  );
}
