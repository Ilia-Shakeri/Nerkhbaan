import React, { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthView } from '../views/AuthView';
import { ForgotPasswordView } from '../views/ForgotPasswordView';
import { ProtectedRoute } from './ProtectedRoute';
import { RequiredPasswordView } from '../views/RequiredPasswordView';

const AlertsView = lazy(() => import('../views/AlertsView').then((module) => ({ default: module.AlertsView })));
const DesktopLayout = lazy(() => import('../layouts/DesktopLayout').then((module) => ({ default: module.DesktopLayout })));
const DashboardView = lazy(() => import('../views/DashboardView').then((module) => ({ default: module.DashboardView })));
const SettingsView = lazy(() => import('../views/SettingsView').then((module) => ({ default: module.SettingsView })));
const ContactView = lazy(() => import('../views/ContactView').then((module) => ({ default: module.ContactView })));
const LegalView = lazy(() => import('../views/LegalView').then((module) => ({ default: module.LegalView })));
const AdvancedReportView = lazy(() => import('../views/AdvancedReportView').then((module) => ({ default: module.AdvancedReportView })));
const SupportView = lazy(() => import('../views/SupportView').then((module) => ({ default: module.SupportView })));
const ChartAnalysisView = lazy(() => import('../views/ChartAnalysisView').then((module) => ({ default: module.ChartAnalysisView })));
const AssistantView = lazy(() => import('../views/AssistantView').then((module) => ({ default: module.AssistantView })));

function DeferredPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="flex min-h-64 items-center justify-center" role="status" aria-label="Loading page"><span className="h-7 w-7 animate-spin rounded-full border-2 border-[#D4AF37] border-t-transparent" /></div>}>
      {children}
    </Suspense>
  );
}

export const AppRouter = () => {
  return (
    <Routes>
      <Route path="/auth" element={<AuthView />} />
      <Route path="/forgot-password" element={<ForgotPasswordView />} />
      {(['privacy', 'terms', 'cookies', 'refunds', 'business'] as const).map((kind) => <Route key={kind} path={`/${kind}`} element={<DeferredPage><LegalView kind={kind} /></DeferredPage>} />)}
      <Route path="/change-password" element={<ProtectedRoute allowPasswordChange><RequiredPasswordView /></ProtectedRoute>} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DeferredPage><DesktopLayout /></DeferredPage>
          </ProtectedRoute>
        }
      >
        <Route index element={<DeferredPage><DashboardView /></DeferredPage>} />
        <Route path="alerts" element={<DeferredPage><AlertsView /></DeferredPage>} />
        <Route path="advanced-report" element={<DeferredPage><AdvancedReportView /></DeferredPage>} />
        <Route path="analysis" element={<DeferredPage><ChartAnalysisView /></DeferredPage>} />
        <Route path="assistant" element={<DeferredPage><AssistantView /></DeferredPage>} />
        <Route path="settings" element={<DeferredPage><SettingsView /></DeferredPage>} />
        <Route path="contact" element={<DeferredPage><ContactView /></DeferredPage>} />
        <Route path="support" element={<DeferredPage><SupportView /></DeferredPage>} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};
