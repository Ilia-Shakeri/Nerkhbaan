import { Navigate, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "@/app/router/ProtectedRoute";

// Import the migrated Electron layout and views
import { DesktopLayout } from "@/app/layout/DesktopLayout";
import AuthView from "@/app/pages/AuthView";
import DashboardView from "@/app/pages/DashboardView";
import AlertsView from "@/app/pages/AlertsView";
import SettingsView from "@/app/pages/SettingsView";

export function AppRouter() {
  return (
    <Routes>
      {/* 1. Use the visually perfect Electron Login View */}
      <Route path="/login" element={<AuthView />} />

      <Route element={<ProtectedRoute />}>
        {/* 2. Use the exact Electron Sidebar/TopBar Layout */}
        <Route element={<DesktopLayout />}>
          <Route path="/" element={<DashboardView />} />
          <Route path="/alerts" element={<AlertsView />} />
          <Route path="/settings" element={<SettingsView />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
