import { useEffect } from "react";
import { BrowserRouter, useNavigate } from "react-router-dom";
import { AppRouter } from "@/app/router/AppRouter";
import { AUTH_UNAUTHORIZED_EVENT } from "@/lib/auth";
import { useAuthStore } from "@/app/store/authStore";

function AuthEventsBridge() {
  const logout = useAuthStore((state) => state.logout);
  const navigate = useNavigate();

  useEffect(() => {
    const onUnauthorized = () => {
      logout();
      navigate("/login", { replace: true });
    };

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
  }, [logout, navigate]);

  return null;
}

export function App() {
  return (
    <BrowserRouter>
      <AuthEventsBridge />
      <AppRouter />
    </BrowserRouter>
  );
}
