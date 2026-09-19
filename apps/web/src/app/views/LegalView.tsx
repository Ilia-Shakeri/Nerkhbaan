import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Languages, Mail, ShieldCheck } from 'lucide-react';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { useAppContext } from '../context/AppContext';
import { LegalLinks } from '../components/LegalLinks';
import { policies, policyTitles, POLICY_VERSION, OPERATOR_EMAIL, type PolicyKind } from '../legal/policies';

export function LegalView({ kind }: { kind: PolicyKind }) {
  const { language, toggleLanguage, theme } = useAppContext();
  const heading = useRef<HTMLHeadingElement>(null);
  const isDark = theme === 'dark';
  const BackIcon = language === 'fa' ? ArrowRight : ArrowLeft;

  useEffect(() => {
    heading.current?.focus();
    document.title = `${policyTitles[kind][language]} | Nerkhbaan`;
  }, [kind, language]);

  return (
    <div className={`flex min-h-dvh flex-col ${isDark ? 'bg-[#080808] text-[#E8D9AE]' : 'bg-[#FFF8E8] text-[#3B2E13]'}`}>
      <header className={`sticky top-0 z-10 border-b backdrop-blur-xl ${isDark ? 'border-white/10 bg-[#080808]/90' : 'border-[#D4AF37]/20 bg-[#FFF8E8]/90'}`}>
        <div className="mx-auto flex min-h-16 max-w-5xl items-center justify-between gap-3 px-4 sm:px-6">
          <Button asChild variant="ghost" className="gap-2"><Link to="/"><BackIcon size={17} />{language === 'fa' ? 'بازگشت به نرخ‌بان' : 'Back to Nerkhbaan'}</Link></Button>
          <Button type="button" variant="outline" onClick={toggleLanguage} className="gap-2"><Languages size={17} />{language === 'fa' ? 'English' : 'فارسی'}</Button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
        <div className={`mb-6 overflow-hidden rounded-3xl border p-6 sm:p-8 ${isDark ? 'border-[#D4AF37]/20 bg-[#11100D]' : 'border-[#D4AF37]/30 bg-[#FFF3D8]'}`}>
          <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#D4AF37] text-[#171006] shadow-sm"><ShieldCheck size={24} /></div>
          <h1 ref={heading} tabIndex={-1} className={`text-3xl font-black focus:outline-none sm:text-4xl ${isDark ? 'text-[#F5E8C2]' : 'text-[#4F390D]'}`}>{policyTitles[kind][language]}</h1>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
            <span className={`rounded-full border px-3 py-1 ${isDark ? 'border-white/10 bg-white/5' : 'border-black/10 bg-white/55'}`}>{language === 'fa' ? 'نسخه متن' : 'Policy version'}: <bdi>{POLICY_VERSION}</bdi></span>
            <a href={`mailto:${OPERATOR_EMAIL}`} className="legal-footer-link inline-flex min-h-11 items-center gap-2 font-semibold"><Mail size={16} /><bdi>{OPERATOR_EMAIL}</bdi></a>
          </div>
        </div>

        <aside className={`mb-8 rounded-2xl border-s-4 p-5 text-sm leading-7 ${isDark ? 'border-s-[#D4AF37] bg-[#15120A] text-[#D9C99E]' : 'border-s-[#B8942A] bg-[#FFF1C8] text-[#654C15]'}`}>
          {language === 'fa' ? 'اطلاعیه خدمت رایگان فعلی: مشخصات مالک و راه تماس اعلام شده‌اند. نشانی عمومی پستی ارائه نشده و جزئیات ارائه‌دهندگان و برنامه جامع نگهداری داده هنوز کامل نیست. این متن گواهی انطباق حقوقی نیست.' : 'Current free-service notice: operator identity and contact are provided. No public postal address is supplied; the provider register and comprehensive retention schedule remain incomplete. This is not certification of legal compliance.'}
        </aside>

        <div className="space-y-4 leading-8">
          {policies[kind].map((section) => (
            <section key={section.title.en} className={`rounded-2xl border p-5 sm:p-6 ${isDark ? 'border-white/10 bg-[#0E0E0E]' : 'border-[#8A6B20]/15 bg-white/65'}`}>
              <h2 className={`mb-2 text-lg font-bold ${isDark ? 'text-[#F1E4BD]' : 'text-[#5B420E]'}`}>{section.title[language]}</h2>
              <p className={isDark ? 'text-[#CDBB8C]' : 'text-[#5F4A1E]'}>{section.body[language]}</p>
            </section>
          ))}
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild variant="primary"><a href={`mailto:${OPERATOR_EMAIL}`}><Mail size={17} />{language === 'fa' ? 'تماس بدون ورود' : 'Contact without sign-in'}</a></Button>
          <Button asChild variant="outline"><Link to="/support">{language === 'fa' ? 'مرکز پشتیبانی' : 'Support centre'}</Link></Button>
        </div>
      </main>

      <LegalLinks variant="footer" />
    </div>
  );
}
