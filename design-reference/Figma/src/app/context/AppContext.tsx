import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

type Theme = 'dark' | 'light';
type Language = 'fa' | 'en';

interface AppContextType {
  theme: Theme;
  toggleTheme: () => void;
  language: Language;
  toggleLanguage: () => void;
  isAuthenticated: boolean;
  login: () => void;
  logout: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider = ({ children }: { children: ReactNode }) => {
  const [theme, setTheme] = useState<Theme>('dark');
  const [language, setLanguage] = useState<Language>('fa');
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  const toggleTheme = () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  const toggleLanguage = () => setLanguage((prev) => (prev === 'fa' ? 'en' : 'fa'));
  const login = () => setIsAuthenticated(true);
  const logout = () => setIsAuthenticated(false);

  useEffect(() => {
    // Apply theme and direction to document
    document.documentElement.classList.remove('dark', 'light');
    document.documentElement.classList.add(theme);
    
    document.documentElement.dir = language === 'fa' ? 'rtl' : 'ltr';
    document.documentElement.lang = language;
    
    // Set font family explicitly to Vazirmatn globally
    document.body.style.fontFamily = "'Vazirmatn', sans-serif";
    
    if (theme === 'dark') {
      document.body.style.backgroundColor = '#0A0A0A';
      document.body.style.color = '#FFFFFF';
    } else {
      document.body.style.backgroundColor = '#F8FAFC'; // Clean white/soft gray
      document.body.style.color = '#0F172A'; // Slate-900
    }
  }, [theme, language]);

  return (
    <AppContext.Provider
      value={{
        theme,
        toggleTheme,
        language,
        toggleLanguage,
        isAuthenticated,
        login,
        logout,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useAppContext = () => {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useAppContext must be used within an AppProvider');
  }
  return context;
};
