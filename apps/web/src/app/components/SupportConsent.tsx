import { Link } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
export function SupportConsent({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  const { language, theme } = useAppContext();
  return <div className={`space-y-2 py-3 text-sm leading-6 ${theme === 'dark' ? 'text-[#E8D9AE]' : 'text-[#3B2E13]'}`}>
    <p>{language === 'fa' ? 'فقط اطلاعات لازم درخواست را بنویسید؛ رمز، اطلاعات بانکی یا مدرک هویت نفرستید.' : 'Send only what the request needs; no passwords, bank details or identity documents.'} <Link className="underline" to="/privacy" target="_blank" rel="noopener">{language === 'fa' ? 'حریم خصوصی (برگه جدید)' : 'Privacy (new tab)'}</Link></p>
    <label className="flex min-h-11 items-start gap-3"><input className="mt-1 h-5 w-5 shrink-0" type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />{language === 'fa' ? 'اجازه می‌دهم پشتیبانی این پیام را برای رسیدگی به درخواستم ذخیره و بررسی کند؛ نه برای بازاریابی.' : 'Support may store and review this message to handle my request, not for marketing.'}</label>
  </div>;
}
