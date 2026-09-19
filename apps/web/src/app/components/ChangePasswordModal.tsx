import React, { useState } from 'react';
import { Modal } from '@nerkhbaan/ui/app/components/ui/Modal';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Lock } from 'lucide-react';
import { toast } from 'sonner';
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
    tooShort: { fa: 'رمز جدید: ۱۰ تا ۱۲۸ کاراکتر، حرف کوچک، بزرگ و عدد', en: 'Use 10–128 characters, lower case, upper case and a digit' },
    failed: { fa: 'رمز عبور فعلی نادرست است', en: 'Current password is incorrect' },
  };

  const resetFields = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
  };

  const closeModal = () => {
    if (isSubmitting) return;
    resetFields();
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 10 || newPassword.length > 128 || !/[a-z]/.test(newPassword) || !/[A-Z]/.test(newPassword) || !/[0-9]/.test(newPassword)) {
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
    <Modal isOpen={isOpen} onClose={closeModal} title={t.title[language]} closeLabel={language === 'fa' ? 'بستن پنجره تغییر رمز' : 'Close password dialog'}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="current-password" className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
            {t.current[language]}
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <Input
              id="current-password"
              name="current-password"
              autoComplete="current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              className="pl-10"
              passwordToggleLabels={{ show: language === 'fa' ? 'نمایش رمز فعلی' : 'Show current password', hide: language === 'fa' ? 'پنهان کردن رمز فعلی' : 'Hide current password' }}
            />
          </div>
        </div>

        <div>
          <label htmlFor="new-password" className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
            {t.new[language]}
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <Input
              id="new-password"
              name="new-password"
              autoComplete="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              className="pl-10"
              passwordToggleLabels={{ show: language === 'fa' ? 'نمایش رمز جدید' : 'Show new password', hide: language === 'fa' ? 'پنهان کردن رمز جدید' : 'Hide new password' }}
            />
          </div>
        </div>

        <div>
          <label htmlFor="confirm-password" className="block text-sm font-medium mb-2 text-gray-700 dark:text-gray-300">
            {t.confirm[language]}
          </label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <Input
              id="confirm-password"
              name="confirm-password"
              autoComplete="new-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="pl-10"
              passwordToggleLabels={{ show: language === 'fa' ? 'نمایش تکرار رمز' : 'Show password confirmation', hide: language === 'fa' ? 'پنهان کردن تکرار رمز' : 'Hide password confirmation' }}
            />
          </div>
        </div>

        <div className="flex gap-3 pt-4">
          <Button type="submit" variant="primary" className="flex-1" disabled={isSubmitting}>
            {isSubmitting ? '...' : t.submit[language]}
          </Button>
          <Button type="button" variant="ghost" className="flex-1" onClick={closeModal} disabled={isSubmitting}>
            {t.cancel[language]}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
