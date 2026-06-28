import React, { useState } from 'react';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Lock } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../services/api';

interface ChangePasswordModalProps {
  isOpen: boolean;
  onClose: () => void;
  language: 'fa' | 'en';
  isDark: boolean;
}

export function ChangePasswordModal({ isOpen, onClose, language, isDark }: ChangePasswordModalProps) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const t = {
    title: { fa: 'تغییر رمز عبور', en: 'Change Password' },
    current: { fa: 'رمز عبور فعلی', en: 'Current Password' },
    new: { fa: 'رمز عبور جدید', en: 'New Password' },
    confirm: { fa: 'تکرار رمز عبور جدید', en: 'Confirm New Password' },
    submit: { fa: 'تغییر رمز', en: 'Change Password' },
    cancel: { fa: 'لغو', en: 'Cancel' },
    success: { fa: 'رمز عبور با موفقیت تغییر کرد', en: 'Password changed successfully' },
    mismatch: { fa: 'رمزهای عبور مطابقت ندارند', en: 'Passwords do not match' },
    tooShort: { fa: 'رمز عبور جدید باید حداقل ۸ کاراکتر باشد', en: 'New password must be at least 8 characters' },
    failed: { fa: 'رمز عبور فعلی نادرست است', en: 'Current password is incorrect' },
  };

  const resetFields = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 8) {
      toast.error(t.tooShort[language]);
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error(t.mismatch[language]);
      return;
    }
    setIsSubmitting(true);
    try {
      await api.auth.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success(t.success[language]);
      resetFields();
      onClose();
    } catch (error: any) {
      toast.error(error?.message || t.failed[language]);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t.title[language]}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
            {t.current[language]}
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <Input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              className="pl-10"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
            {t.new[language]}
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              className="pl-10"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
            {t.confirm[language]}
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <Input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="pl-10"
            />
          </div>
        </div>

        <div className="flex gap-3 pt-4">
          <Button type="submit" variant="primary" className="flex-1" disabled={isSubmitting}>
            {isSubmitting ? '...' : t.submit[language]}
          </Button>
          <Button type="button" variant="ghost" className="flex-1" onClick={onClose} disabled={isSubmitting}>
            {t.cancel[language]}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
