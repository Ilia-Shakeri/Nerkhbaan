import { Link } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
import { policyTitles, type PolicyKind } from '../legal/policies';
export function LegalLinks() {
  const { language, theme } = useAppContext();
  return <nav aria-label={language === 'fa' ? 'اطلاعات حقوقی' : 'Legal information'} className={`flex flex-wrap justify-center gap-x-4 gap-y-1 py-4 text-sm ${theme === 'dark' ? 'text-[#E8D9AE]' : 'text-[#5F4A16]'}`}>
    {(Object.keys(policyTitles) as PolicyKind[]).map((kind) => <Link key={kind} to={`/${kind}`} className="inline-flex min-h-11 items-center underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4">{policyTitles[kind][language]}</Link>)}
    <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center underline">TradingView Lightweight Charts™ · © 2025 TradingView, Inc. {language === 'fa' ? '(برگه جدید)' : '(new tab)'}</a>
  </nav>;
}
