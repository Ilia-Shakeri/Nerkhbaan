import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
import { LegalLinks } from '../components/LegalLinks';
import { policies, policyTitles, POLICY_VERSION, type PolicyKind } from '../legal/policies';
export function LegalView({ kind }: { kind: PolicyKind }) {
  const { language, toggleLanguage, theme } = useAppContext();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); document.title = `${policyTitles[kind][language]} | Nerkhbaan`; }, [kind, language]);
  return <div className={`min-h-dvh px-4 py-6 ${theme === 'dark' ? 'bg-[#0E0E0E] text-[#E8D9AE]' : 'bg-[#FAF3E2] text-[#3B2E13]'}`}>
    <div className="mx-auto max-w-3xl">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <Link to="/" className="inline-flex min-h-11 items-center underline">{language === 'fa' ? 'بازگشت به نرخ‌بان' : 'Back to Nerkhbaan'}</Link>
        <button type="button" onClick={toggleLanguage} className="min-h-11 rounded-lg border border-current px-4">{language === 'fa' ? 'English' : 'فارسی'}</button>
      </header>
      <LegalLinks />
      <main className="space-y-6 leading-8">
        <h1 ref={heading} tabIndex={-1} className="text-2xl font-bold focus:outline-none">{policyTitles[kind][language]}</h1>
        <p className="text-sm">{language === 'fa' ? 'نسخه متن' : 'Policy version'}: <bdi>{POLICY_VERSION}</bdi></p>
        <p className="rounded-lg border border-current p-4">{language === 'fa' ? 'پیش‌نویس: اطلاعات مالک، راه تماس عمومی و مدت نگهداری داده نیاز به تأیید دارد. این متن تأیید حقوقی نیست.' : 'Draft: operator identity, public contact and retention periods need confirmation. This is not legal sign-off.'}</p>
        {policies[kind].map((section) => <section key={section.title.en} className="space-y-2"><h2 className="text-lg font-bold">{section.title[language]}</h2><p>{section.body[language]}</p></section>)}
        <p><Link to="/support" className="underline">{language === 'fa' ? 'مرکز پشتیبانی (نیاز به ورود)' : 'Support centre (sign-in required)'}</Link></p>
      </main>
    </div>
  </div>;
}
