import { create } from "zustand";
import { AUTH_TOKEN_KEY } from "@/lib/auth";

type AuthState = {
  token: string | null;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  logout: () => void;
};

const getInitialToken = () => localStorage.getItem(AUTH_TOKEN_KEY);

export const useAuthStore = create<AuthState>((set) => {
  const initialToken = getInitialToken();

  return {
    token: initialToken,
    isAuthenticated: Boolean(initialToken),
    setToken: (token: string) => {
      localStorage.setItem(AUTH_TOKEN_KEY, token);
      set({ token, isAuthenticated: true });
    },
    logout: () => {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      set({ token: null, isAuthenticated: false });
    }
  };
});
