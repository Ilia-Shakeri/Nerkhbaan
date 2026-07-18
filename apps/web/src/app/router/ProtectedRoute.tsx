import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAppContext } from '../context/AppContext';

export const ProtectedRoute = ({ children, allowPasswordChange = false }: { children: React.ReactNode; allowPasswordChange?: boolean }) => {
  const { isAuthenticated, authReady, mustChangePassword } = useAppContext();
  const location = useLocation();

  if (!authReady) {
    return <div className="min-h-screen bg-[#060606]" aria-busy="true" />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/auth" replace state={{ from: location }} />;
  }

  if (mustChangePassword && !allowPasswordChange) {
    return <Navigate to="/change-password" replace />;
  }

  if (!mustChangePassword && allowPasswordChange) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};
