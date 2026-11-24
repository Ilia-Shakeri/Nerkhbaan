import { ArrowLeft } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';
export function PageBackButton() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { language, isAuthenticated } = useAppContext();
  const label = language === 'fa' ? 'بازگشت' : 'Back';
  return <button type="button" className="page-back-button" aria-label={label} title={label} onClick={() => {
    if ((window.history.state?.idx ?? 0) > 0) navigate(-1);
    else navigate(isAuthenticated ? '/' : '/auth', { replace: pathname === '/auth' || pathname === '/' });
  }}><ArrowLeft size={18} aria-hidden="true" /></button>;
}
