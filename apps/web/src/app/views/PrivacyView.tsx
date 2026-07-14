import React from 'react';
import { useAppContext } from '../context/AppContext';
import { Shield, Lock, Eye, FileText } from 'lucide-react';

export function PrivacyView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';

  const t = {
    title: { fa: 'حریم خصوصی', en: 'Privacy Policy' },
    subtitle: { fa: 'حفاظت از اطلاعات شما اولویت ماست', en: 'Protecting your information is our priority' },
    dataCollection: { fa: 'جمع‌آوری اطلاعات', en: 'Data Collection' },
    dataCollectionText: { fa: 'ما تنها اطلاعات ضروری برای ارائه خدمات را جمع‌آوری می‌کنیم و هرگز اطلاعات شما را با اشخاص ثالث به اشتراک نمی‌گذاریم.', en: 'We only collect essential information required to provide our services and never share your data with third parties.' },
    security: { fa: 'امنیت', en: 'Security' },
    securityText: { fa: 'تمامی اطلاعات شما با استفاده از پروتکل‌های رمزنگاری پیشرفته محافظت می‌شوند.', en: 'All your information is protected using advanced encryption protocols.' },
    transparency: { fa: 'شفافیت', en: 'Transparency' },
    transparencyText: { fa: 'ما به شفافیت کامل در مورد نحوه استفاده از اطلاعات شما متعهد هستیم.', en: 'We are committed to complete transparency about how we use your information.' },
    rights: { fa: 'حقوق شما', en: 'Your Rights' },
    rightsText: { fa: 'شما در هر زمان می‌توانید به اطلاعات خود دسترسی داشته، آن‌ها را ویرایش یا حذف کنید.', en: 'You can access, edit, or delete your information at any time.' }
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

      <div className="space-y-6">
        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40' 
            : 'border-[#D4AF37]/30 bg-white/50'
        }`}>
          <div className="flex items-center gap-4 mb-4">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <FileText size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.dataCollection[language]}
            </h3>
          </div>
          <p className={`text-sm leading-relaxed ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.dataCollectionText[language]}
          </p>
        </div>

        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40' 
            : 'border-[#D4AF37]/30 bg-white/50'
        }`}>
          <div className="flex items-center gap-4 mb-4">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <Lock size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.security[language]}
            </h3>
          </div>
          <p className={`text-sm leading-relaxed ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.securityText[language]}
          </p>
        </div>

        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40' 
            : 'border-[#D4AF37]/30 bg-white/50'
        }`}>
          <div className="flex items-center gap-4 mb-4">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <Eye size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.transparency[language]}
            </h3>
          </div>
          <p className={`text-sm leading-relaxed ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.transparencyText[language]}
          </p>
        </div>

        <div className={`rounded-2xl border p-6 transition-all ${
          isDark 
            ? 'border-[#D4AF37]/20 bg-[#0E0E0E]/40' 
            : 'border-[#D4AF37]/30 bg-white/50'
        }`}>
          <div className="flex items-center gap-4 mb-4">
            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${
              isDark ? 'bg-[#D4AF37]/10' : 'bg-[#D4AF37]/20'
            }`}>
              <Shield size={24} className="text-[#D4AF37]" />
            </div>
            <h3 className={`text-lg font-semibold ${isDark ? 'text-[#E7D49A]' : 'text-[#5F4A16]'}`}>
              {t.rights[language]}
            </h3>
          </div>
          <p className={`text-sm leading-relaxed ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
            {t.rightsText[language]}
          </p>
        </div>
      </div>
    </div>
  );
}
