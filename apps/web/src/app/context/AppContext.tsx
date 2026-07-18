// frontend/src/app/context/AppContext.tsx

import React, {
  useCallback,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState
} from 'react';
import { api, type UserProfile } from '../services/api';

type Language = 'fa' | 'en';
type Theme = 'dark' | 'light';
type CurrencyMode = 'usd' | 'toman';

interface AppContextType {
  isAuthenticated: boolean;
  authReady: boolean;
  mustChangePassword: boolean;

  language: Language;
  theme: Theme;
  currencyMode: CurrencyMode;

  login: (user: UserProfile) => void;
  logout: () => Promise<void>;
  toggleTheme: () => void;
  toggleLanguage: () => void;
  setCurrencyMode: (mode: CurrencyMode) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({
  children
}: {
  children: React.ReactNode;
}) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  const [language, setLanguage] = useState<Language>(() => {
    const savedLanguage = localStorage.getItem('language');
    return savedLanguage === 'en' || savedLanguage === 'fa' ? savedLanguage : 'fa';
  });

  const [theme, setTheme] = useState<Theme>(() => {
    const savedTheme = localStorage.getItem('theme');
    return savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : 'dark';
  });

  const [currencyMode, setCurrencyMode] = useState<CurrencyMode>(() => {
    const saved = localStorage.getItem('currencyMode');
    return saved === 'usd' || saved === 'toman' ? saved : 'usd';
  });

  useEffect(() => {
    let active = true;
    api.auth.me()
      .then((user) => {
        if (active) {
          setIsAuthenticated(true);
          setMustChangePassword(user.must_change_password);
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

    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('currencyMode', currencyMode);
  }, [currencyMode]);

  const login = useCallback((user: UserProfile) => {
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
      // Local state still closes the browser session view when the server is unreachable.
    }
  }, []);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  const toggleLanguage = () => {
    setLanguage((prev) => (prev === 'fa' ? 'en' : 'fa'));
  };

  const value = useMemo(
    () => ({
      isAuthenticated,
      authReady,
      mustChangePassword,

      language,
      theme,
      currencyMode,

      login,
      logout,

      toggleTheme,
      toggleLanguage,
      setCurrencyMode
    }),
    [isAuthenticated, authReady, mustChangePassword, language, theme, currencyMode, login, logout]
  );

  return (
    <AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const context = useContext(AppContext);

  if (!context) {
    throw new Error('useAppContext must be used within AppProvider');
  }

  return context;
}
