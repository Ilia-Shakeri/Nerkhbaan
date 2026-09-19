import { Link } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';

export function AdvancedReportView() {
  const { language, theme } = useAppContext();
  return <section className={`mx-auto max-w-3xl space-y-6 rounded-2xl border p-6 ${theme === 'dark' ? 'border-white/20 text-[#E8D9AE]' : 'border-black/20 text-[#3B2E13]'}`}>
    <h1 className="text-2xl font-bold">{language === 'fa' ? 'گزارش پیشرفته' : 'Advanced report'}</h1>
    <p>{language === 'fa' ? 'برای کاهش انتقال داده، نمودار ثالث در این صفحه بار نمی‌شود. نمودارهای نرخ‌بان در داشبورد در دسترس هستند. پیوند زیر TradingView را باز می‌کند؛ آن سایت نشانی شبکه و مشخصات مرورگر را دریافت می‌کند و سیاست مستقل دارد.' : 'To reduce data sharing, third-party charts do not load here. Nerkhbaan charts remain on the dashboard. The link below opens TradingView, which receives your network address and browser details and uses its own policies.'}</p>
    <div className="flex flex-wrap gap-4">
      <Link to="/" className="inline-flex min-h-11 items-center rounded-lg border border-current px-4 underline">{language === 'fa' ? 'دیدن نمودارهای نرخ‌بان' : 'View Nerkhbaan charts'}</Link>
      <a href="https://www.tradingview.com/chart/?symbol=BINANCE%3ABTCUSDT" target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center rounded-lg border border-current px-4 underline">{language === 'fa' ? 'باز کردن TradingView (برگه جدید)' : 'Open TradingView (new tab)'}</a>
    </div>
    <p><Link to="/cookies" className="underline">{language === 'fa' ? 'سیاست کوکی و ذخیره‌سازی' : 'Cookie and storage policy'}</Link></p>
  </section>;
}
