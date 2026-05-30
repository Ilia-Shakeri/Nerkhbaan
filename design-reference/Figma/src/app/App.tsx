import React from 'react';
import { RouterProvider } from 'react-router';
import { Toaster } from 'sonner';
import { AppProvider, useAppContext } from './context/AppContext';
import { router } from './routes';
import { AuthView } from './views/AuthView';

function AppContent() {
  const { isAuthenticated, language } = useAppContext();

  return (
    <>
      {!isAuthenticated ? (
        <AuthView />
      ) : (
        <RouterProvider router={router} />
      )}
      <Toaster 
        position={language === 'fa' ? 'top-left' : 'top-right'}
        dir={language === 'fa' ? 'rtl' : 'ltr'}
        toastOptions={{
          className: 'dark:bg-[#121212] dark:text-white dark:border-white/10 font-[Vazirmatn]',
        }}
      />
    </>
  );
}

export default function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}
