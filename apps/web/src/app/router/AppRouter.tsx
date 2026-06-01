// src/app/router/AppRouter.tsx
import { Routes, Route, Navigate } from "react-router-dom";
import { ProtectedRoute } from "./ProtectedRoute";

// Use named imports with curly braces to fix the Vite export errors.
// Also ensuring we point to layouts and views directories where your components actually live.
import { DesktopLayout } from "@/app/layouts/DesktopLayout";
import { AuthView } from "@/app/views/AuthView";
import { DashboardView } from "@/app/views/DashboardView";
import { AlertsView } from "@/app/views/AlertsView";
import { SettingsView } from "@/app/views/SettingsView";

export function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<AuthView />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<DesktopLayout />}>
          <Route path="/" element={<DashboardView />} />
          <Route path="/alerts" element={<AlertsView />} />
          <Route path="/settings" element={<SettingsView />} />
        </Route>
      </Route>
      {/* Fallback route */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
