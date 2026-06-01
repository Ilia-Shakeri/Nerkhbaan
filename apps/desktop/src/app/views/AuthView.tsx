import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Activity } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { api } from '../services/api';
import toast from 'react-hot-toast';
import { useNavigate, Link } from 'react-router-dom';

export function AuthView() {
  const { language, login, toggleTheme, toggleLanguage, theme } = useAppContext();
  const isDark = theme === 'dark';
  const navigate = useNavigate();

  const [isLogin, setIsLogin] = useState(true);
  const [identifier, setIdentifier] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fullName, setFullName] = useState('');

  const t = {
    brandName: { fa: 'نرخ‌بان', en: 'Nerkhbaan' },
    brandTagline: { fa: 'ردیابی و هشدار هوشمند قیمت', en: 'Smart price tracking & alerts' },
    login: { fa: 'ورود', en: 'Login' },
    signup: { fa: 'ثبت نام', en: 'Sign Up' },
    fullName: { fa: 'نام کامل', en: 'Full Name' },
    username: { fa: 'نام کاربری', en: 'Username' },
    email: { fa: 'ایمیل', en: 'Email' },
    identifier: { fa: 'نام کاربری یا ایمیل', en: 'Username or Email' },
    password: { fa: 'رمز عبور', en: 'Password' },
    forgot: { fa: 'فراموشی رمز عبور؟', en: 'Forgot password?' },
    signIn: { fa: 'ورود به حساب', en: 'Sign In' },
    createAccount: { fa: 'ایجاد حساب', en: 'Create Account' },
    terms: { fa: 'با ادامه، شما با شرایط استفاده موافقید', en: 'By continuing, you agree to our Terms' },
    success: { fa: 'با موفقیت وارد شدید', en: 'Logged in successfully' },
    created: { fa: 'حساب کاربری ساخته شد', en: 'Account created' },
    failed: { fa: 'خطا در انجام عملیات', en: 'Operation failed' }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      if (isLogin) {
        const response = await api.auth.signin({
          username_or_email: identifier.trim(),
          password
        });
        login(response.access_token);
        toast.success(t.success[language]);
      } else {
        const response = await api.auth.signup({
          username: username.trim(),
          full_name: fullName.trim(),
          email: email.trim(),
          password
        });
        login(response.access_token);
        toast.success(t.created[language]);
      }
      navigate('/');
    } catch (error: any) {
      toast.error(error.message || t.failed[language]);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className={`flex h-screen items-center justify-center p-6 ${isDark ? 'bg-[#060606]' : 'bg-[#FAF3E2]'}`}>
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className={`w-full max-w-md rounded-3xl border p-8 shadow-2xl ${isDark ? 'border-[#D4AF37]/20 bg-[#111]' : 'bg-white'}`}>
        <h2 className="mb-6 text-2xl font-bold text-center">{isLogin ? t.login[language] : t.signup[language]}</h2>
        
        <form onSubmit={handleSubmit} className="space-y-4">
          {!isLogin && (
            <>
              <Input placeholder={t.fullName[language]} value={fullName} onChange={(e) => setFullName(e.target.value)} />
              <Input placeholder={t.username[language]} value={username} onChange={(e) => setUsername(e.target.value)} />
              <Input type="email" placeholder={t.email[language]} value={email} onChange={(e) => setEmail(e.target.value)} />
            </>
          )}

          {isLogin && (
            <div className="space-y-2">
              <Input placeholder={t.identifier[language]} value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
              <div className="flex justify-end">
                <Link to="/forgot-password" className="text-xs text-[#D4AF37] hover:underline">
                  {t.forgot[language]}
                </Link>
              </div>
            </div>
          )}

          <Input type="password" placeholder={t.password[language]} value={password} onChange={(e) => setPassword(e.target.value)} />
          
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? '...' : (isLogin ? t.signIn[language] : t.createAccount[language])}
          </Button>
        </form>

        <button onClick={() => setIsLogin(!isLogin)} className="mt-4 w-full text-sm text-center opacity-70 hover:opacity-100">
          {isLogin ? 'Don\'t have an account? Sign Up' : 'Already have an account? Login'}
        </button>
      </motion.div>
    </div>
  );
}