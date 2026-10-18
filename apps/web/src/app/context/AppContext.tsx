// frontend/src/app/context/AppContext.tsx

import React, {
  useCallback,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { api, type UserProfile } from '../services/api';
import { syncPushSubscription } from '@/pwa/push';
import { requestLogout } from '../services/logout';
import { logoutIsPending, subscribeLogoutStatus } from '../services/logout-state';
import { readPreference, rememberPreference } from '../legal/storage';
import { revokeDesktopNoticeSession, startDesktopNoticeSession } from '../services/desktop-notification-session';

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
  const authGeneration = useRef(0);

  const [language, setLanguage] = useState<Language>(() => {
    const savedLanguage = readPreference('language');
    return savedLanguage === 'en' || savedLanguage === 'fa' ? savedLanguage : 'fa';
  });

  const [theme, setTheme] = useState<Theme>(() => {
    const savedTheme = readPreference('theme');
    return savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : 'dark';
  });

  const [currencyMode, updateCurrencyMode] = useState<CurrencyMode>(() => {
    const saved = readPreference('currencyMode');
    return saved === 'usd' || saved === 'toman' ? saved : 'usd';
  });

  useEffect(() => {
    let active = true;
    const generation = ++authGeneration.current;
    const current = () => active && authGeneration.current === generation && !logoutIsPending();
    if (logoutIsPending()) {
      setAuthReady(true);
      return;
    }
    api.auth.me()
      .then((user) => {
        if (current()) {
          startDesktopNoticeSession();
          setIsAuthenticated(true);
          setMustChangePassword(user.must_change_password);
          // A subscription created before sign-in is stored with no account
          // attached, so re-send it once we know who the user is.
          void syncPushSubscription();
        }
      })
      .catch(() => {
        if (current()) {
          revokeDesktopNoticeSession();
          setIsAuthenticated(false);
          setMustChangePassword(false);
        }
      })
      .finally(() => {
        if (current()) setAuthReady(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => subscribeLogoutStatus(() => {
    if (!logoutIsPending()) return;
    authGeneration.current++;
    revokeDesktopNoticeSession();
    setIsAuthenticated(false);
    setMustChangePassword(false);
    setAuthReady(true);
  }), []);

  useEffect(() => {
    document.documentElement.dir = language === 'fa' ? 'rtl' : 'ltr';
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {

    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  const setCurrencyMode = (mode: CurrencyMode) => {
    rememberPreference('currencyMode', mode);
    updateCurrencyMode(mode);
  };

  const login = useCallback((user: UserProfile) => {
    if (logoutIsPending()) return;
    authGeneration.current++;
    startDesktopNoticeSession();
    setIsAuthenticated(true);
    setMustChangePassword(user.must_change_password);
    setAuthReady(true);
    void syncPushSubscription();
  }, []);

  const logout = useCallback(() => {
    revokeDesktopNoticeSession();
    authGeneration.current++;
    setIsAuthenticated(false);
    setMustChangePassword(false);
    setAuthReady(true);
    return requestLogout().catch(() => undefined);
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    rememberPreference('theme', next);
    setTheme(next);
  };

  const toggleLanguage = () => {
    const next = language === 'fa' ? 'en' : 'fa';
    rememberPreference('language', next);
    setLanguage(next);
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
