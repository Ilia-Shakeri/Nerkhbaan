import { createBrowserRouter } from 'react-router';
import { DesktopLayout } from './layouts/DesktopLayout';
import { DashboardView } from './views/DashboardView';
import { AlertsView } from './views/AlertsView';
import { SettingsView } from './views/SettingsView';

export const router = createBrowserRouter([
  {
    path: '/',
    Component: DesktopLayout,
    children: [
      { index: true, Component: DashboardView },
      { path: 'alerts', Component: AlertsView },
      { path: 'settings', Component: SettingsView },
    ],
  },
]);
