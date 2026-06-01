import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAppContext } from "@/app/context/AppContext";

export function ProtectedRoute() {
  const { isAuthenticated } = useAppContext();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
