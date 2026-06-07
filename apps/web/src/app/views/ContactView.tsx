import React from 'react';
import { useAppContext } from '../context/AppContext';
import { Mail, Phone, MapPin, MessageSquare } from 'lucide-react';

export function ContactView() {
  const { language, theme } = useAppContext() as any;
  const isDark = theme === 'dark';

  const t = {
    title: { fa: 'تماس با ما', en: 'Contact Us' },
    subtitle: { fa: 'ما همیشه آماده شنیدن نظرات شما هستیم', en: 'We are always ready to hear from you' },
    email: { fa: 'ایمیل', en: 'Email' },
    phone: { fa: 'تلفن', en: 'Phone' },
    address: { fa: 'آدرس', en: 'Address' },
    support: { fa: 'پشتیبانی', en: 'Support' },
    emailValue: { fa: 'support@nerkhbaan.com', en: 'support@nerkhbaan.com' },
    phoneValue: { fa: '+98 21 1234 5678', en: '+98 21 1234 5678' },
    addressValue: { fa: 'تهران، ایران', en: 'Tehran, Iran' },
    supportValue: { fa: '۲۴/۷ پشتیبانی آنلاین', en: '24/7 Online Support' }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="text-center space-y-2">
        <h1 className={`text-3xl font-bold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
          {t.title[language]}
        </h1>
        <p className={`text-sm ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
          {t.subtitle[language]}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40 hover:bg-[#0E0E0E]/60' 
            : 'border-[#D4AF37]/30 bg-white/50 hover:bg-white/80'
        }`}>
          <div className="flex items-center gap-4 mb-3">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <Mail size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.email[language]}
            </h3>
          </div>
          <p className={`text-sm ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.emailValue[language]}
          </p>
        </div>

        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40 hover:bg-[#0E0E0E]/60' 
            : 'border-[#D4AF37]/30 bg-white/50 hover:bg-white/80'
        }`}>
          <div className="flex items-center gap-4 mb-3">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <Phone size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.phone[language]}
            </h3>
          </div>
          <p className={`text-sm ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.phoneValue[language]}
          </p>
        </div>

        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40 hover:bg-[#0E0E0E]/60' 
            : 'border-[#D4AF37]/30 bg-white/50 hover:bg-white/80'
        }`}>
          <div className="flex items-center gap-4 mb-3">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <MapPin size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.address[language]}
            </h3>
          </div>
          <p className={`text-sm ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.addressValue[language]}
          </p>
        </div>

        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40 hover:bg-[#0E0E0E]/60' 
            : 'border-[#D4AF37]/30 bg-white/50 hover:bg-white/80'
        }`}>
          <div className="flex items-center gap-4 mb-3">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <MessageSquare size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.support[language]}
            </h3>
          </div>
          <p className={`text-sm ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.supportValue[language]}
          </p>
        </div>
      </div>
    </div>
  );
}
