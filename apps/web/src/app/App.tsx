import { BrowserRouter, HashRouter, useNavigate } from "react-router-dom";
import { AppRouter } from "@/app/router/AppRouter";
import { AppProvider, useAppContext } from "@/app/context/AppContext";
import { Toaster } from "sonner";
import { useEffect, useState, useRef } from "react";
import { SplashScreen } from "@/app/components/SplashScreen";
import { applyPendingUpdate } from "@/pwa/registerServiceWorker";
import { motion, AnimatePresence, MotionConfig } from "motion/react";

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

function AppContent() {
  const [showSplash, setShowSplash] = useState(() => {
    const prefersLessMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return !prefersLessMotion && !sessionStorage.getItem('splash-shown');
  });
  const { language, theme } = useAppContext();

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
            className="fixed left-1/2 z-50 -translate-x-1/2 rounded-full bg-red-500 px-6 py-3 text-sm font-semibold text-white shadow-lg"
            style={{ top: 'max(1rem, env(safe-area-inset-top))' }}
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
            className="fixed left-1/2 z-50 -translate-x-1/2 rounded-full bg-emerald-600 px-6 py-3 text-sm font-semibold text-white shadow-lg"
            style={{ bottom: 'max(1rem, env(safe-area-inset-bottom))' }}
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
      <MotionConfig reducedMotion="user">
        <Router>
          <AuthEventsBridge />
          <AppContent />
          <Toaster position="top-center" richColors />
        </Router>
      </MotionConfig>
    </AppProvider>
  );
}
