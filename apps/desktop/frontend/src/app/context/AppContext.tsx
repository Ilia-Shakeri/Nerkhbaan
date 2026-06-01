// frontend/src/app/context/AppContext.tsx

import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState
} from 'react';

type Language = 'fa' | 'en';
type Theme = 'dark' | 'light';

interface AppContextType {
  isAuthenticated: boolean;
  token: string | null;

  language: Language;
  theme: Theme;

  login: (token: string) => void;
  logout: () => void;

  toggleTheme: () => void;
  toggleLanguage: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({
  children
}: {
  children: React.ReactNode;
}) {
  // Initialize token from localStorage
  const [token, setToken] = useState<string | null>(() => {
    return localStorage.getItem('authToken');
  });

  const [language, setLanguage] = useState<Language>(() => {
    const savedLanguage = localStorage.getItem('language');
    return savedLanguage === 'en' || savedLanguage === 'fa' ? savedLanguage : 'fa';
  });

  const [theme, setTheme] = useState<Theme>(() => {
    const savedTheme = localStorage.getItem('theme');
    return savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : 'dark';
  });

  const isAuthenticated = !!token;

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

  const login = (newToken: string) => {
    localStorage.setItem('authToken', newToken);
    setToken(newToken);
  };

  const logout = () => {
    localStorage.removeItem('authToken');
    setToken(null);
  };

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  const toggleLanguage = () => {
    setLanguage((prev) => (prev === 'fa' ? 'en' : 'fa'));
  };

  const value = useMemo(
    () => ({
      isAuthenticated,
      token,

      language,
      theme,

      login,
      logout,

      toggleTheme,
      toggleLanguage
    }),
    [isAuthenticated, token, language, theme]
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
