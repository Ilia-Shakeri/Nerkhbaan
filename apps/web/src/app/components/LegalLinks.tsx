import { Link } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
import { policyTitles, type PolicyKind } from '../legal/policies';
import logo from '../../logo/logo.png';

export function LegalLinks({ variant = 'compact' }: { variant?: 'compact' | 'footer' }) {
  const { language, theme } = useAppContext();
  const links = (
    <nav aria-label={language === 'fa' ? 'اطلاعات حقوقی' : 'Legal information'} className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1">
      {(Object.keys(policyTitles) as PolicyKind[]).map((kind) => (
        <Link key={kind} to={`/${kind}`} className="legal-footer-link inline-flex min-h-11 items-center underline-offset-4">
          {policyTitles[kind][language]}
        </Link>
      ))}
    </nav>
  );

  if (variant === 'compact') {
    return <div className={`py-4 text-sm ${theme === 'dark' ? 'text-[#E8D9AE]' : 'text-[#5F4A16]'}`}>{links}</div>;
  }

  return (
    <footer className={`mt-auto border-t ${theme === 'dark' ? 'border-[#D4AF37]/15 bg-[#090909] text-[#CDBB8C]' : 'border-[#D4AF37]/25 bg-[#FFF3D8] text-[#6E5317]'}`}>
      <div className="mx-auto flex w-full max-w-7xl flex-col items-center gap-4 px-4 py-7 text-center text-sm sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <img src={logo} alt="" aria-hidden="true" className="h-10 w-10 object-contain" />
          <div className="text-start">
            <p className={`font-bold ${theme === 'dark' ? 'text-[#F1E4BD]' : 'text-[#4F3A0E]'}`}>{language === 'fa' ? 'نرخ‌بان' : 'Nerkhbaan'}</p>
            <p className="text-xs">{language === 'fa' ? 'داده بازار با منبع و زمان روشن' : 'Market data with clear source and time'}</p>
          </div>
        </div>
        {links}
        <div className={`flex flex-col items-center gap-1 border-t pt-4 text-xs sm:flex-row sm:gap-3 ${theme === 'dark' ? 'border-white/10' : 'border-black/10'}`}>
          <span>© 2026 Ilia Shakeri</span>
          <span className="hidden sm:inline" aria-hidden="true">•</span>
          <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer" className="legal-footer-link inline-flex min-h-11 items-center">
            TradingView Lightweight Charts™ · © 2025 TradingView, Inc.
            <span className="sr-only"> {language === 'fa' ? '(برگه جدید)' : '(new tab)'}</span>
          </a>
        </div>
      </div>
    </footer>
  );
}
