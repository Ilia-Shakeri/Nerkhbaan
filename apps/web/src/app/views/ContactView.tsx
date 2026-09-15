import React from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare } from 'lucide-react';
import { useAppContext } from '../context/AppContext';

export function ContactView() {
  const navigate = useNavigate();
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';

  const t = {
    title: { fa: 'تماس با ما', en: 'Contact Us' },
    subtitle: {
      fa: 'درخواست خود را امن و مستقیم برای تیم پشتیبانی بفرستید',
      en: 'Send your request securely to the support team',
    },
    support: { fa: 'پشتیبانی', en: 'Support' },
    supportValue: { fa: 'ورود به مرکز پشتیبانی', en: 'Open Support Center' },
  };

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="space-y-2 text-center">
        <h1 className={`text-3xl font-bold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
          {t.title[language]}
        </h1>
        <p className={`text-sm ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
          {t.subtitle[language]}
        </p>
      </div>

      <div className="mx-auto max-w-xl">
        <button
          type="button"
          onClick={() => navigate('/support')}
          className={`w-full rounded-2xl border p-6 text-start transition-[background-color,border-color,box-shadow,transform] active:scale-[0.99] ${
            isDark
              ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40 hover:bg-[#0E0E0E]/70'
              : 'border-[#D4AF37]/30 bg-white/50 hover:bg-white/90'
          }`}
        >
          <div className="mb-3 flex items-center gap-4">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'}`}>
              <MessageSquare size={24} className="text-[#D4AF37]" />
            </div>
            <h2 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.support[language]}
            </h2>
          </div>
          <p className={`text-sm ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.supportValue[language]}
          </p>
        </button>
      </div>
    </div>
  );
}
