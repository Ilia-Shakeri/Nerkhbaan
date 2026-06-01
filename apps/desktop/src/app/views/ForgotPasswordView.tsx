import React, { useState } from 'react';
import { motion } from 'motion/react';
import { ArrowLeft } from 'lucide-react';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { api } from '../services/api';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';

export function ForgotPasswordView() {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    
    setIsSubmitting(true);
    try {
      await api.auth.forgotPassword(email);
      toast.success('Reset instructions sent to your email.');
      navigate('/auth');
    } catch (error: any) {
      toast.error('Failed to send reset email.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center p-6 bg-[#060606]">
      <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="w-full max-w-md rounded-3xl border border-[#D4AF37]/20 bg-[#111] p-8">
        <button onClick={() => navigate('/auth')} className="mb-6 flex items-center text-sm text-[#D4AF37] hover:underline">
          <ArrowLeft size={16} className="mr-2" /> Back to Login
        </button>
        <h2 className="mb-2 text-2xl font-bold text-white">Reset Password</h2>
        <p className="mb-6 text-sm text-gray-400">Enter your email address to receive recovery instructions.</p>
        
        <form onSubmit={handleReset} className="space-y-4">
          <Input type="email" placeholder="email@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? 'Sending...' : 'Send Instructions'}
          </Button>
        </form>
      </motion.div>
    </div>
  );
}