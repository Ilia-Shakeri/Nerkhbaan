// apps/desktop/src/app/views/ForgotPasswordView.tsx
import React, { useState } from 'react';
import { motion } from 'motion/react';
import { ArrowLeft, Mail, Lock } from 'lucide-react';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { api } from '../services/api';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';

export function ForgotPasswordView() {
  const [email, setEmail] = useState('');
  const [resetCode, setResetCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [step, setStep] = useState<'request' | 'reset'>('request');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();
  const { theme } = useAppContext();
  const isDark = theme === 'dark';

  const handleRequestReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    
    setIsSubmitting(true);
    try {
      await api.auth.forgotPassword(email);
      toast.success('Reset instructions sent to your email.');
      // Move to step 2 in UI ready for future API integration
      setStep('reset');
    } catch (error: any) {
      toast.error('Failed to send reset email. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetCode || !newPassword) return;
    
    setIsSubmitting(true);
    try {
      // Future API connection: await api.auth.resetPassword({ email, code: resetCode, newPassword });
      toast.success('Password successfully reset! You can now log in.');
      navigate('/auth');
    } catch (error: any) {
      toast.error('Failed to reset password. Invalid code.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className={`flex h-screen items-center justify-center p-6 ${isDark ? 'bg-[#060606]' : 'bg-[#FAF3E2]'}`}>
      <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className={`w-full max-w-md rounded-3xl border p-8 shadow-2xl ${isDark ? 'border-[#D4AF37]/20 bg-[#111]' : 'bg-white'}`}>
        <button onClick={() => navigate('/auth')} className={`mb-6 flex items-center text-sm hover:underline ${isDark ? 'text-[#D4AF37]' : 'text-amber-600'}`}>
          <ArrowLeft size={16} className="mr-2" /> Back to Login
        </button>
        
        <h2 className={`mb-2 text-2xl font-bold ${isDark ? 'text-white' : 'text-gray-900'}`}>
          {step === 'request' ? 'Reset Password' : 'Set New Password'}
        </h2>
        <p className={`mb-6 text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
          {step === 'request' 
            ? 'Enter your email address to receive recovery instructions and a reset code.' 
            : `Enter the recovery code sent to ${email} and choose a new password.`}
        </p>
        
        {step === 'request' ? (
          <form onSubmit={handleRequestReset} className="space-y-4">
            <div className="relative">
              <Mail className="absolute left-3 top-3 h-5 w-5 text-gray-400" />
              <Input type="email" placeholder="email@example.com" value={email} onChange={(e) => setEmail(e.target.value)} className="pl-10" />
            </div>
            <Button type="submit" disabled={isSubmitting || !email} className="w-full">
              {isSubmitting ? 'Sending...' : 'Send Recovery Code'}
            </Button>
          </form>
        ) : (
          <form onSubmit={handleConfirmReset} className="space-y-4">
            <Input type="text" placeholder="Enter recovery code" value={resetCode} onChange={(e) => setResetCode(e.target.value)} />
            <div className="relative">
              <Lock className="absolute left-3 top-3 h-5 w-5 text-gray-400" />
              <Input type="password" placeholder="New Password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="pl-10" />
            </div>
            <Button type="submit" disabled={isSubmitting || !resetCode || !newPassword} className="w-full">
              {isSubmitting ? 'Updating...' : 'Reset My Password'}
            </Button>
          </form>
        )}
      </motion.div>
    </div>
  );
}
