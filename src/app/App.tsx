import { BrowserRouter, useNavigate } from "react-router-dom";
import { AppRouter } from "@/app/router/AppRouter";
import { AppProvider, useAppContext } from "@/app/context/AppContext";
import { Toaster } from "sonner";
import { useEffect } from "react";

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

export function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <AuthEventsBridge />
        <AppRouter />
        <Toaster position="top-center" richColors />
      </BrowserRouter>
    </AppProvider>
  );
}
