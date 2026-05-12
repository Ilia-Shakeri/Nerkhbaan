import React from 'react';
import { HashRouter } from 'react-router-dom';
import { Toaster } from 'sonner';
import { useAppContext } from './context/AppContext';
import { AppRoutes } from './routes';

function App() {
  const { language } = useAppContext();

  return (
    <HashRouter>
      <AppRoutes />
      <Toaster 
        position={language === 'fa' ? 'top-left' : 'top-right'}
        dir={language === 'fa' ? 'rtl' : 'ltr'}
        richColors
      />
    </HashRouter>
  );
}

export default App;
