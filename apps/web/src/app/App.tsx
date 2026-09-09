import { BrowserRouter, HashRouter, useNavigate } from "react-router-dom";
import { AppRouter } from "@/app/router/AppRouter";
import { AppProvider, useAppContext } from "@/app/context/AppContext";
import { Toaster } from "sonner";
import { useEffect, useState, useRef } from "react";
import { SplashScreen } from "@/app/components/SplashScreen";
import { applyPendingUpdate } from "@/pwa/registerServiceWorker";
import { motion, AnimatePresence } from "motion/react";

function AuthEventsBridge() {
  const { logout } = useAppContext();
  const navigate = useNavigate();

  useEffect(() => {
    const onUnauthorized = () => {
  logout();
  navigate("/auth", { replace: true });
};

    window.addEventListener("auth-expired", onUnauthorized);
    return () => window.removeEventListener("auth-expired", onUnauthorized);
  }, [logout, navigate]);

  return null;
}

// The splash is branding, not a loading gate. A live price dashboard that
// blocks for seconds on every session start is worse than one that shows data
// immediately, so it is capped short and only shown once per session.
const SPLASH_DURATION_MS = 1200;

function AppContent() {
  const [showSplash, setShowSplash] = useState(() => {
    return !sessionStorage.getItem('splash-shown');
  });
  const { language, theme } = useAppContext();

  useEffect(() => {
    if (!showSplash) return;
    const readyTimer = setTimeout(() => {
      sessionStorage.setItem('splash-shown', 'true');
      setShowSplash(false);
    }, SPLASH_DURATION_MS);
    return () => clearTimeout(readyTimer);
  }, [showSplash]);

  const [showOfflineBanner, setShowOfflineBanner] = useState(false);
  const [updateReady, setUpdateReady] = useState(false);
  const stabilityTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSplashComplete = () => {
    sessionStorage.setItem('splash-shown', 'true');
    setShowSplash(false);
  };

  useEffect(() => {
    const onUpdate = () => setUpdateReady(true);
    window.addEventListener('app-update-available', onUpdate);
    return () => window.removeEventListener('app-update-available', onUpdate);
  }, []);

  useEffect(() => {
    const handleOnline = () => {
      if (stabilityTimer.current) clearTimeout(stabilityTimer.current);
      stabilityTimer.current = setTimeout(() => {
        setShowOfflineBanner(false);
      }, 1500);
    };
    const handleOffline = () => {
      setShowOfflineBanner(true);
    };
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      if (stabilityTimer.current) clearTimeout(stabilityTimer.current);
    };
  }, []);

  return showSplash ? (
    <SplashScreen onComplete={handleSplashComplete} language={language} theme={theme} />
  ) : (
    <>
      <AnimatePresence>
        {showOfflineBanner && (
          <motion.div
            initial={{ y: -100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -100, opacity: 0 }}
            className="fixed top-4 left-1/2 -translate-x-1/2 z-50 px-6 py-3 rounded-full bg-red-500 text-white text-sm font-semibold shadow-lg"
          >
            {language === 'fa' ? 'شما آفلاین هستید' : 'You are offline'}
          </motion.div>
        )}
        {updateReady && (
          <motion.button
            type="button"
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            onClick={() => { void applyPendingUpdate(); }}
            className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 px-6 py-3 rounded-full bg-emerald-600 text-white text-sm font-semibold shadow-lg"
          >
            {language === 'fa' ? 'نسخه جدید آماده است — بازخوانی' : 'New version ready — reload'}
          </motion.button>
        )}
      </AnimatePresence>
      <AppRouter />
    </>
  );
}

export function App() {
  const Router = window.electronAPI ? HashRouter : BrowserRouter;
  return (
    <AppProvider>
      <Router>
        <AuthEventsBridge />
        <AppContent />
        <Toaster position="top-center" richColors />
      </Router>
    </AppProvider>
  );
}
