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
import { ChartAnalysisView } from './views/ChartAnalysisView';
import { AssistantView } from './views/AssistantView';
import { SupportView } from './views/SupportView';
import { RequiredPasswordView } from './views/RequiredPasswordView';

const ProtectedRoute = ({ children, allowPasswordChange = false }: { children: React.ReactNode; allowPasswordChange?: boolean }) => {
  const { isAuthenticated, authReady, mustChangePassword } = useAppContext();

  if (!authReady) {
    return <div className="min-h-screen bg-[#060606]" aria-busy="true" />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/auth" replace />;
  }

  if (mustChangePassword && !allowPasswordChange) {
    return <Navigate to="/change-password" replace />;
  }

  if (!mustChangePassword && allowPasswordChange) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};

export const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/auth" element={<AuthView />} />
      <Route path="/forgot-password" element={<ForgotPasswordView />} />
      <Route path="/change-password" element={<ProtectedRoute allowPasswordChange><RequiredPasswordView /></ProtectedRoute>} />

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
        <Route path="analysis" element={<ChartAnalysisView />} />
        <Route path="assistant" element={<AssistantView />} />
        <Route path="settings" element={<SettingsView />} />
        <Route path="contact" element={<ContactView />} />
        <Route path="support" element={<SupportView />} />
        <Route path="privacy" element={<PrivacyView />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};
