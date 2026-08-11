import { BrowserRouter, useNavigate } from "react-router-dom";
import { AppRouter } from "@/app/router/AppRouter";
import { AppProvider, useAppContext } from "@/app/context/AppContext";
import { Toaster } from "sonner";
import { useEffect, useState, useRef } from "react";
import { SplashScreen } from "@/app/components/SplashScreen";
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

function AppContent() {
  const [isMobile, setIsMobile] = useState(false);
  const [showSplash, setShowSplash] = useState(() => {
    return !sessionStorage.getItem('splash-shown');
  });
  const { language, theme } = useAppContext();
  const [splashReady, setSplashReady] = useState(false);

  useEffect(() => {
    const checkMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    setIsMobile(checkMobile);

    if (showSplash) {
      const readyTimer = setTimeout(() => {
        setSplashReady(true);
      }, isMobile ? 4500 : 3000);
      return () => clearTimeout(readyTimer);
    }
  }, [showSplash, isMobile]);

  const [showOfflineBanner, setShowOfflineBanner] = useState(false);
  const stabilityTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSplashComplete = () => {
    sessionStorage.setItem('splash-shown', 'true');
    setShowSplash(false);
  };

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

  return showSplash && !splashReady ? (
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
      </AnimatePresence>
      <AppRouter />
    </>
  );
}

export function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <AuthEventsBridge />
        <AppContent />
        <Toaster position="top-center" richColors />
      </BrowserRouter>
    </AppProvider>
  );
}
