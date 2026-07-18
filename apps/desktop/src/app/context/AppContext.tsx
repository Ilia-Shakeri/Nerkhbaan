import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, clearCredentials, getStoredAccessToken, storeCredentials, type CurrencyMode, type SessionCredentials, type UserProfile } from '../services/api';

type Language = 'fa' | 'en';
type Theme = 'dark' | 'light';

interface AppContextType {
  isAuthenticated: boolean;
  authReady: boolean;
  mustChangePassword: boolean;
  language: Language;
  theme: Theme;
  currencyMode: CurrencyMode;
  login: (credentials: SessionCredentials, user: UserProfile) => Promise<void>;
  logout: () => Promise<void>;
  toggleTheme: () => void;
  toggleLanguage: () => void;
  setCurrencyMode: (mode: CurrencyMode) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [language, setLanguage] = useState<Language>(() => {
    const saved = localStorage.getItem('language');
    return saved === 'en' || saved === 'fa' ? saved : 'fa';
  });
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('theme');
    return saved === 'light' || saved === 'dark' ? saved : 'dark';
  });
  const [currencyMode, setCurrencyModeState] = useState<CurrencyMode>(() => {
    const saved = localStorage.getItem('currencyMode');
    return saved === 'usd' || saved === 'toman' ? saved : 'toman';
  });

  useEffect(() => {
    let active = true;
    getStoredAccessToken()
      .then(async (token) => {
        if (!token) return false;
        const user = await api.auth.me();
        return user;
      })
      .then((user) => {
        if (active) {
          setIsAuthenticated(Boolean(user));
          setMustChangePassword(user?.must_change_password ?? false);
        }
      })
      .catch(() => {
        if (active) {
          setIsAuthenticated(false);
          setMustChangePassword(false);
        }
      })
      .finally(() => {
        if (active) setAuthReady(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem('language', language);
    document.documentElement.dir = language === 'fa' ? 'rtl' : 'ltr';
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    localStorage.setItem('theme', theme);
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('currencyMode', currencyMode);
  }, [currencyMode]);

  const login = useCallback(async (credentials: SessionCredentials, user: UserProfile) => {
    await storeCredentials(credentials);
    setIsAuthenticated(true);
    setMustChangePassword(user.must_change_password);
    setAuthReady(true);
  }, []);

  const logout = useCallback(async () => {
    setIsAuthenticated(false);
    setMustChangePassword(false);
    setAuthReady(true);
    try {
      await api.auth.signout();
    } catch {
      // The local secure credential must still be removed when the server is offline.
    } finally {
      await clearCredentials();
    }
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => void logout();
    window.addEventListener('auth-expired', handleAuthExpired);
    return () => window.removeEventListener('auth-expired', handleAuthExpired);
  }, [logout]);

  const value = useMemo(() => ({
    isAuthenticated,
    authReady,
    mustChangePassword,
    language,
    theme,
    currencyMode,
    login,
    logout,
    toggleTheme: () => setTheme((current) => current === 'dark' ? 'light' : 'dark'),
    toggleLanguage: () => setLanguage((current) => current === 'fa' ? 'en' : 'fa'),
    setCurrencyMode: setCurrencyModeState,
  }), [authReady, currencyMode, isAuthenticated, language, login, logout, mustChangePassword, theme]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppContext() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useAppContext must be used within AppProvider');
  return context;
}
