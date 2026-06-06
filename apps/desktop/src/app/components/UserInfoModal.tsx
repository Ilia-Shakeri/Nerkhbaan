import React from 'react';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { User, Calendar, Phone, Hash } from 'lucide-react';

interface UserInfoModalProps {
  isOpen: boolean;
  onClose: () => void;
  language: 'fa' | 'en';
  isDark: boolean;
}

export function UserInfoModal({ isOpen, onClose, language, isDark }: UserInfoModalProps) {
  const t = {
    title: { fa: 'اطلاعات کاربری', en: 'User Info' },
    fullName: { fa: 'نام و نام خانوادگی', en: 'Full Name' },
    accountAge: { fa: 'تاریخ ثبت نام', en: 'Account Age' },
    phone: { fa: 'شماره تماس', en: 'Phone Number' },
    userId: { fa: 'شناسه کاربری', en: 'User ID' },
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t.title[language]}>
      <div className="space-y-4">
        <div className="flex items-center gap-3 p-3 rounded-lg bg-gray-50 dark:bg-[#1a1a1a]">
          <User className="text-gray-500 dark:text-gray-400" size={20} />
          <div className="flex-1">
            <div className="text-xs text-gray-500 dark:text-gray-400">{t.fullName[language]}</div>
            <div className="font-medium text-gray-900 dark:text-white">Admin User</div>
          </div>
        </div>

        <div className="flex items-center gap-3 p-3 rounded-lg bg-gray-50 dark:bg-[#1a1a1a]">
          <Calendar className="text-gray-500 dark:text-gray-400" size={20} />
          <div className="flex-1">
            <div className="text-xs text-gray-500 dark:text-gray-400">{t.accountAge[language]}</div>
            <div className="font-medium text-gray-900 dark:text-white">2024-01-01</div>
          </div>
        </div>

        <div className="flex items-center gap-3 p-3 rounded-lg bg-gray-50 dark:bg-[#1a1a1a]">
          <Phone className="text-gray-500 dark:text-gray-400" size={20} />
          <div className="flex-1">
            <div className="text-xs text-gray-500 dark:text-gray-400">{t.phone[language]}</div>
            <div className="font-medium text-gray-900 dark:text-white">+98 912 345 6789</div>
          </div>
        </div>

        <div className="flex items-center gap-3 p-3 rounded-lg bg-gray-50 dark:bg-[#1a1a1a]">
          <Hash className="text-gray-500 dark:text-gray-400" size={20} />
          <div className="flex-1">
            <div className="text-xs text-gray-500 dark:text-gray-400">{t.userId[language]}</div>
            <div className="font-medium text-gray-900 dark:text-white font-mono">admin-001</div>
          </div>
        </div>
      </div>
    </Modal>
  );
}
