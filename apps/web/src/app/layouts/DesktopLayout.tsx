import React, { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, Navigate, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import {
  Settings,
  LayoutDashboard,
  BellRing,
  UserCircle2,
  Menu,
  X,
  Sun,
  Moon,
  Languages,
  PanelLeftClose,
  PanelLeftOpen,
  Bell,
  ChevronDown,
  LogOut,
  User,
  KeyRound,
  MessageCircle,
  Sparkles,
  Bot,
  AlertTriangle
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { UserInfoModal } from '../components/UserInfoModal';
import { ChangePasswordModal } from '../components/ChangePasswordModal';
import logo from '../../logo/logo.png';
import { BarChart3 } from 'lucide-react';
import { api, type NotificationItem } from '../services/api';

const NAV_ITEMS = [
  { path: '/', label: { fa: 'داشبورد', en: 'Dashboard' }, icon: LayoutDashboard },
  { path: '/alerts', label: { fa: 'هشدارها', en: 'Alerts' }, icon: BellRing },
  { path: '/advanced-report', label: { fa: 'گزارش پیشرفته', en: 'Advanced Report' }, icon: BarChart3 },
  { path: '/analysis', label: { fa: 'تحلیل هوشمند', en: 'Smart Analysis' }, icon: Sparkles },
  { path: '/assistant', label: { fa: 'دستیار هوشمند', en: 'Smart Assistant' }, icon: Bot },
  { path: '/settings', label: { fa: 'تنظیمات', en: 'Settings' }, icon: Settings },
];

export function DesktopLayout() {
  const { language, theme, logout, toggleTheme, toggleLanguage, isAuthenticated, currencyMode, setCurrencyMode } = useAppContext();
  const isDark = theme === 'dark';

  const navigate = useNavigate();
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [isUserInfoOpen, setIsUserInfoOpen] = useState(false);
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);
  const [apiAlert, setApiAlert] = useState<{ id: number; key: string } | null>(null);
  const [hasDegradedSources, setHasDegradedSources] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationsUnavailable, setNotificationsUnavailable] = useState(false);
  const mobileNavigationRef = useRef<HTMLElement>(null);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const showApiError = (event: Event) => {
      const detail = (event as CustomEvent<{ key: string; message: string }>).detail;
      setApiAlert({
        id: Date.now(),
        key: detail?.key || 'unknown',
      });
    };
    const clearApiError = (event: Event) => {
      const key = (event as CustomEvent<{ key: string }>).detail?.key || 'unknown';
      setApiAlert((current) => current?.key === key ? null : current);
    };
    window.addEventListener('api-error', showApiError);
    window.addEventListener('api-error-clear', clearApiError);
    return () => {
      window.removeEventListener('api-error', showApiError);
      window.removeEventListener('api-error-clear', clearApiError);
    };
  }, []);

  useEffect(() => {
    if (!apiAlert) return;
    const timer = window.setTimeout(() => setApiAlert(null), 5_000);
    return () => window.clearTimeout(timer);
  }, [apiAlert]);

  useEffect(() => {
    const updatePricingHealth = (event: Event) => {
      const detail = (event as CustomEvent<{ degraded?: boolean }>).detail;
      setHasDegradedSources(Boolean(detail?.degraded));
    };
    window.addEventListener('pricing-health', updatePricingHealth);
    return () => window.removeEventListener('pricing-health', updatePricingHealth);
  }, []);

  useEffect(() => {
    if (!isNotificationsOpen || !isAuthenticated) return;
    let active = true;
    setNotificationsLoading(true);
    setNotificationsUnavailable(false);
    api.notifications.list()
      .then((items) => {
        if (active) setNotifications(items);
      })
      .catch(() => {
        if (active) {
          setNotifications([]);
          setNotificationsUnavailable(true);
        }
      })
      .finally(() => {
        if (active) setNotificationsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated, isNotificationsOpen]);

  useEffect(() => {
    if (!isSidebarOpen && !isNotificationsOpen && !isUserMenuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setIsSidebarOpen(false);
      setIsNotificationsOpen(false);
      setIsUserMenuOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [isNotificationsOpen, isSidebarOpen, isUserMenuOpen]);

  useEffect(() => {
    if (!isSidebarOpen) return;
    const panel = mobileNavigationRef.current;
    const focusable = () => Array.from(panel?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    focusable()[0]?.focus();
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', trapFocus);
    return () => {
      window.removeEventListener('keydown', trapFocus);
      mobileMenuButtonRef.current?.focus();
    };
  }, [isSidebarOpen]);

  if (!isAuthenticated) {
    return <Navigate to="/auth" replace />;
  }

  const SidebarContent = ({
    collapsed = false,
    canCollapse = false,
  }: {
    collapsed?: boolean;
    canCollapse?: boolean;
  }) => (
    <>
      <div className="group relative flex h-20 shrink-0 items-center justify-center border-b border-[#D4AF37]/15">
        <NavLink
          to="/"
          onClick={() => setIsSidebarOpen(false)}
          className="transition-opacity hover:opacity-80"
        >
          <img
          src={logo}
          alt={language === 'fa' ? 'لوگو نرخ‌بان' : 'Nerkhbaan logo'}
          className={`object-contain transition-[width,height] duration-200 ease-out ${collapsed ? 'h-12 w-12' : 'h-16 w-16'}`}
        />
        </NavLink>
        {canCollapse && (
          <button
            type="button"
            onClick={() => setIsSidebarCollapsed((prev) => !prev)}
            className={`absolute bottom-1 end-1 flex h-11 w-11 items-center justify-center rounded-xl border opacity-0 shadow-lg backdrop-blur transition-[opacity,background-color,color] group-hover:opacity-100 group-focus-within:opacity-100 ${
              isDark
                ? 'border-white/10 bg-[#171717]/95 text-[#D4AF37] hover:bg-[#222222]'
                : 'border-black/10 bg-[#FFF3D8]/95 text-[#8A6B20] hover:bg-[#F2E4BC]'
            }`}
            aria-label={
              language === 'fa'
                ? isSidebarCollapsed ? 'باز کردن منو' : 'بستن منو'
                : isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'
            }
            title={
              language === 'fa'
                ? isSidebarCollapsed ? 'باز کردن منو' : 'بستن منو'
                : isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'
            }
          >
            {isSidebarCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </button>
        )}
      </div>

      <nav className="flex-1 space-y-2 p-4 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            onClick={() => setIsSidebarOpen(false)}
            className={({ isActive }) =>
              `min-h-11 flex items-center rounded-xl px-4 py-3 text-sm font-medium transition-[background-color,color,box-shadow] ${
                isActive
                  ? 'bg-[#D4AF37] text-[#0A0A0A] shadow-[0_4px_20px_rgba(212,175,55,0.25)]'
                  : isDark
                    ? 'text-[#CFBE91] hover:bg-[#191919] hover:text-[#F6E8C2]'
                    : 'text-[#8A6B20] hover:bg-[#F6EBD0] hover:text-[#5D4614]'
              } ${collapsed ? 'justify-center px-2' : 'gap-3'}`
            }
          >
            <item.icon size={18} />
            <AnimatePresence initial={false}>
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -4 }}
                  transition={{ duration: 0.16, ease: 'easeOut' }}
                  className="whitespace-nowrap"
                >
                  {item.label[language]}
                </motion.span>
              )}
            </AnimatePresence>
          </NavLink>
        ))}
      </nav>

      <div className="shrink-0 border-t border-[#D4AF37]/15 p-4">
        <div className="flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={toggleTheme}
            className={`flex h-11 w-11 items-center justify-center rounded-xl transition-colors active:scale-95 ${
              isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'
            }`}
            aria-label={language === 'fa' ? (isDark ? 'فعال کردن پوسته روشن' : 'فعال کردن پوسته تیره') : (isDark ? 'Use light theme' : 'Use dark theme')}
            aria-pressed={isDark}
          >
            {isDark ? <Sun size={18} /> : <Moon size={18} />}
          </button>

          <button
            type="button"
            onClick={toggleLanguage}
            className={`flex h-11 w-11 items-center justify-center rounded-xl transition-colors active:scale-95 ${
              isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'
            }`}
            aria-label={language === 'fa' ? 'تغییر زبان به انگلیسی' : 'Switch language to Persian'}
          >
            <Languages size={18} />
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div
      className={`flex h-dvh w-full overflow-hidden transition-colors duration-200 ${
        isDark ? 'bg-[#050505] text-[#F2E8CC]' : 'bg-[#FFF8E8] text-[#4A3913]'
      }`}
    >
      <AnimatePresence>
        {apiAlert && (
          <motion.div
            key={apiAlert.id}
            initial={{ opacity: 0, y: -70, x: '-50%' }}
            animate={{ opacity: 1, y: 0, x: '-50%' }}
            exit={{ opacity: 0, y: -70, x: '-50%' }}
            transition={{ type: 'spring', stiffness: 360, damping: 28 }}
            className={`pointer-events-none fixed left-1/2 top-4 z-[100] flex w-[min(92vw,30rem)] items-center justify-center gap-2 rounded-2xl border px-4 py-3 text-center text-sm font-bold shadow-2xl backdrop-blur-xl ${
              isDark
                ? 'border-[#D4AF37]/35 bg-[#151107]/95 text-[#F3E2AB] shadow-black/50'
                : 'border-[#B8942A]/40 bg-[#FFF6D8]/95 text-[#6E5317] shadow-[#8A6B20]/20'
            }`}
            role="alert"
          >
            <AlertTriangle size={18} className="shrink-0 text-amber-500" />
            <span>
              {language === 'fa'
                ? 'خطا در ارتباط با سرویس. لطفاً کمی بعد دوباره تلاش کنید.'
                : 'Service request failed. Please try again shortly.'}
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Desktop Sidebar */}
      <motion.aside
        initial={false}
        animate={{ width: isSidebarCollapsed ? 80 : 256 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.34 }}
        className={`hidden overflow-hidden flex-col border-e border-[#D4AF37]/15 lg:flex ${
          isDark ? 'bg-[#0B0B0B]' : 'bg-[#FFF3D8]'
        }`}
      >
        <SidebarContent collapsed={isSidebarCollapsed} canCollapse />
      </motion.aside>

      {/* Mobile Drawer Overlay */}
      <AnimatePresence>
        {isSidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsSidebarOpen(false)}
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      {/* Mobile Sidebar */}
      <AnimatePresence>
        {isSidebarOpen && (
          <motion.aside
            ref={mobileNavigationRef}
            initial={{ x: language === 'fa' ? '100%' : '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: language === 'fa' ? '100%' : '-100%' }}
            transition={{ type: 'spring', bounce: 0, duration: 0.34 }}
            className={`fixed bottom-0 top-0 z-50 flex w-72 flex-col ${
              isDark ? 'bg-[#0B0B0B]' : 'bg-[#FFF3D8]'
            } lg:hidden ${
              language === 'fa' ? 'right-0 border-l border-[#D4AF37]/15' : 'left-0 border-r border-[#D4AF37]/15'
            }`}
            id="mobile-navigation"
            role="dialog"
            aria-modal="true"
            aria-label={language === 'fa' ? 'منوی اصلی' : 'Main navigation'}
            style={{ paddingTop: 'env(safe-area-inset-top)', paddingBottom: 'env(safe-area-inset-bottom)' }}
          >
            <button 
              type="button"
              onClick={() => setIsSidebarOpen(false)}
              className={`absolute end-4 top-4 flex h-11 w-11 items-center justify-center rounded-xl ${isDark ? 'text-[#CFBE91] hover:text-[#F6E8C2]' : 'text-[#8A6B20] hover:text-[#5D4614]'}`}
              aria-label={language === 'fa' ? 'بستن منو' : 'Close menu'}
            >
              <X size={20} />
            </button>
            <SidebarContent />
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Main Content Area */}
      <div className="relative flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header
          className={`relative z-10 flex min-h-16 shrink-0 items-center justify-between border-b border-[#D4AF37]/12 px-4 backdrop-blur-md transition-colors duration-200 sm:px-6 ${
            isDark ? 'bg-[#0B0B0B]/95' : 'bg-[#FFF3D8]/95'
          }`}
          style={{ paddingTop: 'env(safe-area-inset-top)' }}
        >
          <div className="hidden lg:block" aria-hidden="true" />

          <div className="flex items-center gap-4 lg:hidden">
             <button 
                ref={mobileMenuButtonRef}
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                className={`-mx-2 flex h-11 w-11 items-center justify-center rounded-xl ${isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'}`}
                aria-label={language === 'fa' ? 'باز کردن منو' : 'Open menu'}
                aria-expanded={isSidebarOpen}
                aria-controls="mobile-navigation"
             >
                <Menu size={20} />
             </button>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            {/* Currency Toggle */}
            <div className={`relative flex h-9 items-center gap-0.5 rounded-full p-1 ${
              isDark
                ? 'bg-[#141414] border border-[#D4AF37]/20'
                : 'bg-[#F5E9CB] border border-[#D4AF37]/30'
            }`}>
              {(['usd', 'toman'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setCurrencyMode(mode)}
                  className={`relative rounded-full px-3 py-1 text-xs font-semibold tracking-wide transition-colors duration-150 ${
                    currencyMode === mode
                      ? 'text-[#0A0A0A]'
                      : isDark ? 'text-[#9C8A5D] hover:text-[#CFBE91]' : 'text-[#A07830] hover:text-[#6E5317]'
                  }`}
                  aria-pressed={currencyMode === mode}
                >
                  {currencyMode === mode && (
                    <motion.div
                      layoutId="currency-pill"
                      className="absolute inset-0 rounded-full bg-gradient-to-br from-[#E2C05A] via-[#D4AF37] to-[#B8942A] shadow-[0_1px_6px_rgba(212,175,55,0.45)]"
                      transition={{ type: 'spring', stiffness: 420, damping: 30 }}
                    />
                  )}
                  <span className="relative z-10">
                    {mode === 'usd' ? 'USD' : (language === 'fa' ? 'تومان' : 'TMN')}
                  </span>
                </button>
              ))}
            </div>

            {/* Notification Bell */}
            <div className="relative">
              <button
                onClick={() => setIsNotificationsOpen(!isNotificationsOpen)}
                className={`relative flex h-11 w-11 items-center justify-center rounded-xl transition-colors active:scale-95 ${
                  isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'
                }`}
                aria-label={language === 'fa' ? 'اعلان‌ها' : 'Notifications'}
                aria-expanded={isNotificationsOpen}
                aria-controls="notifications-panel"
              >
                <Bell size={20} />
                {(hasDegradedSources || notifications.some((item) => !item.read_at)) && (
                  <span className="absolute right-2.5 top-2.5 flex h-2 w-2 rounded-full bg-[#EF4444] shadow-[0_0_8px_0_rgba(239,68,68,0.8)]" />
                )}
              </button>

              {/* Notifications Dropdown */}
              <AnimatePresence>
                {isNotificationsOpen && (
                  <>
                    <motion.div
                       initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                       transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                       onClick={() => setIsNotificationsOpen(false)}
                       className="fixed inset-0 z-10" 
                    />
                    <motion.div
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      transition={{ type: 'spring', bounce: 0, duration: 0.28 }}
                      className={`absolute end-0 top-12 z-20 w-80 rounded-2xl border border-[#D4AF37]/20 p-2 shadow-xl ${
                        isDark ? 'bg-[#0E0E0E]' : 'bg-[#FFF9EA]'
                      }`}
                      id="notifications-panel"
                      role="region"
                      aria-label={language === 'fa' ? 'فهرست اعلان‌ها' : 'Notification list'}
                    >
                      <div className={`mb-2 px-3 pt-2 text-sm font-semibold ${isDark ? 'text-[#F5EBCD]' : 'text-[#5D4614]'}`}>
                        {language === 'fa' ? 'اعلان‌ها' : 'Notifications'}
                      </div>

                      {hasDegradedSources && (
                        <div className={`mx-2 mb-3 rounded-xl border px-3 py-2 text-xs ${
                          isDark ? 'border-amber-500/35 bg-amber-500/10 text-amber-200' : 'border-amber-400/50 bg-amber-100/90 text-amber-800'
                        }`}>
                          {language === 'fa'
                            ? '⚠️ برخی از منابع تامین قیمت در دسترس نیستند. آخرین قیمت‌های ذخیره شده نمایش داده می‌شوند.'
                            : '⚠️ Some pricing providers are unavailable. The latest cached prices are being shown.'}
                        </div>
                      )}

                      <div className="space-y-1">
                        {notificationsLoading && (
                          <div className={`p-4 text-center text-xs ${isDark ? 'text-[#9C8A5D]' : 'text-[#8A6B20]'}`}>
                            {language === 'fa' ? 'در حال دریافت...' : 'Loading...'}
                          </div>
                        )}
                        {!notificationsLoading && notificationsUnavailable && (
                          <div className={`p-4 text-center text-xs ${isDark ? 'text-amber-300' : 'text-amber-700'}`}>
                            {language === 'fa' ? 'سرویس اعلان در دسترس نیست.' : 'Notification service is unavailable.'}
                          </div>
                        )}
                        {!notificationsLoading && !notificationsUnavailable && notifications.length === 0 && !hasDegradedSources && (
                          <div className={`p-4 text-center text-xs ${isDark ? 'text-[#9C8A5D]' : 'text-[#8A6B20]'}`}>
                            {language === 'fa' ? 'اعلان تازه‌ای نیست.' : 'No notifications yet.'}
                          </div>
                        )}
                        {notifications.map((notif) => (
                          <button
                            key={notif.id}
                            type="button"
                            onClick={() => {
                              if (notif.read_at) return;
                              void api.notifications.markRead(notif.id).then((updated) => {
                                setNotifications((current) => current.map((item) => item.id === notif.id ? updated : item));
                              }).catch(() => setNotificationsUnavailable(true));
                            }}
                            className={`relative flex cursor-pointer flex-col gap-1 rounded-xl p-3 text-sm transition-colors ${
                              isDark ? 'hover:bg-[#171717]' : 'hover:bg-[#F2E4BC]'
                            } w-full text-start`}
                          >
                            {!notif.read_at && (
                              <span className="absolute start-1.5 top-3.5 h-1.5 w-1.5 rounded-full bg-[#EF4444]" />
                            )}
                            <div className={`font-medium ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'} ${!notif.read_at ? 'ps-3' : ''}`}>
                              {notif.title || notif.message}
                            </div>
                            <div className={`text-xs ${isDark ? 'text-[#9C8A5D]' : 'text-[#8A6B20]'} ${!notif.read_at ? 'ps-3' : ''}`}>
                              {new Date(notif.created_at).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}
                            </div>
                          </button>
                        ))}
                      </div>
                    </motion.div>
                  </>
                )}
              </AnimatePresence>
            </div>

            <div className="mx-1 h-6 w-px bg-[#D4AF37]/20" />

            {/* User Dropdown Menu */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                className="flex min-h-11 min-w-11 cursor-pointer items-center gap-2 rounded-xl pe-1 transition-colors hover:bg-black/5 active:scale-[0.98] dark:hover:bg-white/5"
                aria-label={language === 'fa' ? 'منوی کاربر' : 'User menu'}
                aria-expanded={isUserMenuOpen}
                aria-controls="user-menu"
              >
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#D4AF37] text-[#0A0A0A]">
                  <UserCircle2 size={16} />
                </div>
                <span className={`hidden text-sm font-medium sm:block ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
                  {language === 'fa' ? 'کاربر' : 'User'}
                </span>
                <ChevronDown size={14} className={`hidden sm:block ${isDark ? 'text-[#9C8A5D]' : 'text-[#8A6B20]'}`} />
              </button>

              <AnimatePresence>
                {isUserMenuOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-30"
                      onClick={() => setIsUserMenuOpen(false)}
                    />
                    <motion.div
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      transition={{ type: 'spring', bounce: 0, duration: 0.24 }}
                      className={`absolute ${language === 'fa' ? 'left-0' : 'right-0'} top-full mt-2 z-40 w-48 overflow-hidden rounded-xl border shadow-xl ${
                        isDark
                          ? 'border-white/10 bg-[#1A1A1A]'
                          : 'border-black/10 bg-white'
                      }`}
                      id="user-menu"
                      role="menu"
                    >
                      <div className="p-1">
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            setIsUserInfoOpen(true);
                          }}
                          className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                            isDark
                              ? 'text-[#E2D3AA] hover:bg-[#252525]'
                              : 'text-[#6E5317] hover:bg-[#F6EBD0]'
                          }`}
                        >
                          <User size={16} />
                          <span>{language === 'fa' ? 'اطلاعات کاربری' : 'User Info'}</span>
                        </button>

                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            setIsChangePasswordOpen(true);
                          }}
                          className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                            isDark
                              ? 'text-[#E2D3AA] hover:bg-[#252525]'
                              : 'text-[#6E5317] hover:bg-[#F6EBD0]'
                          }`}
                        >
                          <KeyRound size={16} />
                          <span>{language === 'fa' ? 'تغییر رمز عبور' : 'Change Password'}</span>
                        </button>

                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            navigate('/support');
                          }}
                          className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                            isDark
                              ? 'text-[#E2D3AA] hover:bg-[#252525]'
                              : 'text-[#6E5317] hover:bg-[#F6EBD0]'
                          }`}
                        >
                          <MessageCircle size={16} />
                          <span>{language === 'fa' ? 'پشتیبانی' : 'Support'}</span>
                        </button>

                        <div className="my-1 h-px bg-[#D4AF37]/15" />

                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            logout();
                          }}
                          className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                            isDark
                              ? 'text-red-400 hover:bg-red-500/10'
                              : 'text-red-600 hover:bg-red-50'
                          }`}
                        >
                          <LogOut size={16} />
                          <span>{language === 'fa' ? 'خروج از حساب' : 'Logout'}</span>
                        </button>
                      </div>
                    </motion.div>
                  </>
                )}
              </AnimatePresence>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>

      <UserInfoModal
        isOpen={isUserInfoOpen}
        onClose={() => setIsUserInfoOpen(false)}
        language={language}
        isDark={isDark}
      />

      <ChangePasswordModal
        isOpen={isChangePasswordOpen}
        onClose={() => setIsChangePasswordOpen(false)}
        language={language}
        isDark={isDark}
      />
    </div>
  );
}
