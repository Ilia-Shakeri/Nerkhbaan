import React, { useEffect, useState } from 'react';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { AtSign, Calendar, Hash, Loader2, Mail, User } from 'lucide-react';
import { api, type UserProfile } from '../services/api';

interface UserInfoModalProps {
  isOpen: boolean;
  onClose: () => void;
  language: 'fa' | 'en';
  isDark: boolean;
}

export function UserInfoModal({ isOpen, onClose, language }: UserInfoModalProps) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    let active = true;
    setIsLoading(true);
    setHasError(false);
    api.auth.me()
      .then((value) => {
        if (active) setProfile(value);
      })
      .catch(() => {
        if (active) setHasError(true);
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isOpen]);

  const t = {
    title: { fa: 'اطلاعات کاربری', en: 'User Info' },
    fullName: { fa: 'نام و نام خانوادگی', en: 'Full Name' },
    username: { fa: 'نام کاربری', en: 'Username' },
    email: { fa: 'ایمیل', en: 'Email' },
    memberSince: { fa: 'تاریخ ثبت نام', en: 'Member Since' },
    userId: { fa: 'شناسه کاربری', en: 'User ID' },
    loadFail: { fa: 'دریافت اطلاعات کاربر ناموفق بود', en: 'Failed to load user info' },
  };

  const rows = profile ? [
    { icon: User, label: t.fullName[language], value: profile.full_name },
    { icon: AtSign, label: t.username[language], value: profile.username },
    { icon: Mail, label: t.email[language], value: profile.email },
    {
      icon: Calendar,
      label: t.memberSince[language],
      value: new Date(profile.created_at).toLocaleDateString(language === 'fa' ? 'fa-IR' : 'en-US'),
    },
    { icon: Hash, label: t.userId[language], value: String(profile.id) },
  ] : [];

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t.title[language]}>
      <div className="space-y-4">
        {isLoading ? (
          <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-[#D4AF37]" /></div>
        ) : hasError ? (
          <p className="py-6 text-center text-sm text-red-500">{t.loadFail[language]}</p>
        ) : rows.map(({ icon: Icon, label, value }) => (
          <div key={label} className="flex items-center gap-3 rounded-lg bg-gray-50 p-3 dark:bg-[#1a1a1a]">
            <Icon className="text-gray-500 dark:text-gray-400" size={20} />
            <div className="flex-1">
              <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
              <div className="font-medium text-gray-900 dark:text-white" dir="ltr">{value}</div>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}
