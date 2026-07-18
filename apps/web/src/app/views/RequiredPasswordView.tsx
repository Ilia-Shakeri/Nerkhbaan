import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { api } from '../services/api';
import { useAppContext } from '../context/AppContext';

export function RequiredPasswordView() {
  const navigate = useNavigate();
  const { language, logout } = useAppContext();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (newPassword.length < 8 || newPassword !== confirmation) {
      toast.error(language === 'fa' ? 'رمز جدید معتبر نیست یا تکرار آن یکسان نیست.' : 'New password is invalid or confirmation does not match.');
      return;
    }
    setSaving(true);
    try {
      await api.auth.changePassword({ current_password: currentPassword, new_password: newPassword });
      await logout();
      navigate('/auth', { replace: true });
      toast.success(language === 'fa' ? 'رمز عوض شد. دوباره وارد شوید.' : 'Password changed. Sign in again.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Password change failed');
    } finally {
      setSaving(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-[#060606] p-6"><Card className="w-full max-w-md space-y-5 border-[#D4AF37]/30 p-6"><div className="flex items-center gap-3"><Lock className="text-[#D4AF37]" /><div><h1 className="text-xl font-bold text-white">{language === 'fa' ? 'تغییر رمز الزامی' : 'Password change required'}</h1><p className="mt-1 text-sm text-slate-400">{language === 'fa' ? 'پیش از ادامه، رمز موقت را عوض کنید.' : 'Change the temporary password before continuing.'}</p></div></div><form onSubmit={submit} className="space-y-3"><Input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} placeholder={language === 'fa' ? 'رمز فعلی' : 'Current password'} required /><Input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder={language === 'fa' ? 'رمز جدید' : 'New password'} minLength={8} required /><Input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={language === 'fa' ? 'تکرار رمز جدید' : 'Confirm new password'} minLength={8} required /><Button type="submit" disabled={saving} className="w-full bg-[#D4AF37] text-black">{saving ? '...' : language === 'fa' ? 'تغییر رمز' : 'Change password'}</Button></form></Card></main>;
}
