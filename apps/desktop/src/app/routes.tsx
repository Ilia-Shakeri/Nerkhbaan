import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAppContext } from './context/AppContext';
import { DesktopLayout } from './layouts/DesktopLayout';
import { DashboardView } from './views/DashboardView';
import { AlertsView } from './views/AlertsView';
import { SettingsView } from './views/SettingsView';
import { ContactView } from './views/ContactView';
import { PrivacyView } from './views/PrivacyView';
import { AuthView } from './views/AuthView';
import { ForgotPasswordView } from './views/ForgotPasswordView';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated } = useAppContext();
  const token = localStorage.getItem('authToken');

  if (!isAuthenticated && !token) {
    return <Navigate to="/auth" replace />;
  }

  return <>{children}</>;
};

export const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/auth" element={<AuthView />} />
      <Route path="/forgot-password" element={<ForgotPasswordView />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DesktopLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardView />} />
        <Route path="alerts" element={<AlertsView />} />
        <Route path="settings" element={<SettingsView />} />
        <Route path="contact" element={<ContactView />} />
        <Route path="privacy" element={<PrivacyView />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};
