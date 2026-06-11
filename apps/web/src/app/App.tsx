import { BrowserRouter, useNavigate } from "react-router-dom";
import { AppRouter } from "@/app/router/AppRouter";
import { AppProvider, useAppContext } from "@/app/context/AppContext";
import { Toaster } from "sonner";
import { useEffect, useState } from "react";
import { SplashScreen } from "@/app/components/SplashScreen";

function AuthEventsBridge() {
  const { logout } = useAppContext();
  const navigate = useNavigate();

  useEffect(() => {
    const onUnauthorized = () => {
      logout();
      navigate("/login", { replace: true });
    };

    window.addEventListener("auth-expired", onUnauthorized);
    return () => window.removeEventListener("auth-expired", onUnauthorized);
  }, [logout, navigate]);

  return null;
}

function AppContent() {
  const [showSplash, setShowSplash] = useState(() => {
    return !sessionStorage.getItem('splash-shown');
  });
  const { language, theme } = useAppContext();

  const handleSplashComplete = () => {
    sessionStorage.setItem('splash-shown', 'true');
    setShowSplash(false);
  };

  return showSplash ? (
    <SplashScreen onComplete={handleSplashComplete} language={language} theme={theme} />
  ) : (
    <AppRouter />
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
