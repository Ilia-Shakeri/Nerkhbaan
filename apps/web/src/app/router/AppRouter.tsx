import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { DesktopLayout } from '../layouts/DesktopLayout';
import { DashboardView } from '../views/DashboardView';
import { AlertsView } from '../views/AlertsView';
import { SettingsView } from '../views/SettingsView';
import { ContactView } from '../views/ContactView';
import { PrivacyView } from '../views/PrivacyView';
import { AuthView } from '../views/AuthView';
import { ForgotPasswordView } from '../views/ForgotPasswordView';
import { AdvancedReportView } from '../views/AdvancedReportView';
import { SupportView } from '../views/SupportView';
import { ProtectedRoute } from './ProtectedRoute';

export const AppRouter = () => {
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
        <Route path="advanced-report" element={<AdvancedReportView />} />
        <Route path="settings" element={<SettingsView />} />
        <Route path="contact" element={<ContactView />} />
        <Route path="privacy" element={<PrivacyView />} />
        <Route path="support" element={<SupportView />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};
