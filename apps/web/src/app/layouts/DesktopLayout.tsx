import React, { useState } from 'react';
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
  Bot
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { UserInfoModal } from '../components/UserInfoModal';
import { ChangePasswordModal } from '../components/ChangePasswordModal';
import logo from '../../logo/logo.png';
import { BarChart3 } from 'lucide-react';

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

  if (!isAuthenticated) {
    return <Navigate to="/auth" replace />;
  }

  const notifications = [
    {
      id: 1,
      title: {
        fa: 'قیمت طلا به حد مورد نظر رسید 🔔',
        en: 'Gold reached your target price 🔔'
      },
      time: { fa: '۱۰ دقیقه پیش', en: '10 minutes ago' },
      read: false
    },
    {
      id: 2,
      title: {
        fa: 'بیت‌کوین از ۶۵,۰۰۰ عبور کرد 🚀',
        en: 'Bitcoin crossed 65,000 🚀'
      },
      time: { fa: '۱ ساعت پیش', en: '1 hour ago' },
      read: true
    }
  ];

  const hasDegradedSources = false;

  const SidebarContent = ({ collapsed = false }: { collapsed?: boolean }) => (
    <>
      <div className="flex h-20 shrink-0 items-center justify-center border-b border-[#D4AF37]/15">
        <NavLink
          to="/"
          onClick={() => setIsSidebarOpen(false)}
          className="transition-opacity hover:opacity-80"
        >
          <img
          src={logo}
          alt={language === 'fa' ? 'لوگو نرخ‌بان' : 'Nerkhbaan logo'}
          className={`object-contain transition-all duration-300 ease-out ${collapsed ? 'h-12 w-12' : 'h-16 w-16'}`}
        />
        </NavLink>
      </div>

      <nav className="flex-1 space-y-2 p-4 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            onClick={() => setIsSidebarOpen(false)}
            className={({ isActive }) =>
              `flex items-center rounded-xl px-4 py-3 text-sm font-medium transition-all ${
                isActive
                  ? 'bg-[#D4AF37] text-[#0A0A0A] shadow-[0_4px_20px_rgba(212,175,55,0.25)]'
                  : isDark
                    ? 'text-[#CFBE91] hover:bg-[#191919] hover:text-[#F6E8C2]'
                    : 'text-[#8A6B20] hover:bg-[#F6EBD0] hover:text-[#5D4614]'
              } ${collapsed ? 'justify-center px-2' : 'gap-3'}`
            }
          >
            <item.icon size={18} />
            <motion.span
              initial={false}
              animate={
                collapsed
                  ? { opacity: 0, width: 0, x: -6 }
                  : { opacity: 1, width: 'auto', x: 0 }
              }
              transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden whitespace-nowrap"
            >
              {item.label[language]}
            </motion.span>
          </NavLink>
        ))}
      </nav>

      <div className="shrink-0 border-t border-[#D4AF37]/15 p-4">
        <div className="flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={toggleTheme}
            className={`flex h-10 w-10 items-center justify-center rounded-xl transition-colors ${
              isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'
            }`}
            aria-label="Toggle theme"
          >
            {isDark ? <Sun size={18} /> : <Moon size={18} />}
          </button>

          <button
            type="button"
            onClick={toggleLanguage}
            className={`flex h-10 w-10 items-center justify-center rounded-xl transition-colors ${
              isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'
            }`}
            aria-label="Toggle language"
          >
            <Languages size={18} />
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div
      className={`flex h-screen w-full overflow-hidden transition-colors duration-500 ${
        isDark ? 'bg-[#050505] text-[#F2E8CC]' : 'bg-[#FFF8E8] text-[#4A3913]'
      }`}
    >
      {/* Desktop Sidebar */}
      <motion.aside
        initial={false}
        animate={{ width: isSidebarCollapsed ? 80 : 256 }}
        transition={{ type: 'spring', stiffness: 170, damping: 26, mass: 1.05 }}
        className={`hidden flex-col border-e border-[#D4AF37]/15 lg:flex ${
          isDark ? 'bg-[#0B0B0B]' : 'bg-[#FFF3D8]'
        } will-change-[width]`}
      >
        <SidebarContent collapsed={isSidebarCollapsed} />
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
          />
        )}
      </AnimatePresence>

      {/* Mobile Sidebar */}
      <AnimatePresence>
        {isSidebarOpen && (
          <motion.aside
            initial={{ x: language === 'fa' ? '100%' : '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: language === 'fa' ? '100%' : '-100%' }}
            transition={{ type: 'spring', bounce: 0.08, duration: 0.56 }}
            className={`fixed bottom-0 top-0 z-50 flex w-72 flex-col ${
              isDark ? 'bg-[#0B0B0B]' : 'bg-[#FFF3D8]'
            } lg:hidden ${
              language === 'fa' ? 'right-0 border-l border-[#D4AF37]/15' : 'left-0 border-r border-[#D4AF37]/15'
            }`}
          >
            <button 
              onClick={() => setIsSidebarOpen(false)}
              className={`absolute end-4 top-4 p-2 ${isDark ? 'text-[#CFBE91] hover:text-[#F6E8C2]' : 'text-[#8A6B20] hover:text-[#5D4614]'}`}
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
          className={`z-10 flex h-16 shrink-0 items-center justify-between border-b border-[#D4AF37]/12 px-6 backdrop-blur-md transition-colors duration-500 ${
            isDark ? 'bg-[#0B0B0B]/95' : 'bg-[#FFF3D8]/95'
          }`}
        >
          <div className="hidden lg:flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsSidebarCollapsed((prev) => !prev)}
              className={`rounded-lg p-2 transition-colors ${
                isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'
              }`}
              aria-label={isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isSidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
          </div>

          <div className="flex items-center gap-4 lg:hidden">
             <button 
                onClick={() => setIsSidebarOpen(true)}
                className={`-mx-2 rounded-lg p-2 ${isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'}`}
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
                className={`relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors ${
                  isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'
                }`}
              >
                <Bell size={20} />
                <span className="absolute right-2.5 top-2.5 flex h-2 w-2 rounded-full bg-[#EF4444] shadow-[0_0_8px_0_rgba(239,68,68,0.8)]" />
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
                      transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
                      className={`absolute end-0 top-12 z-20 w-80 rounded-2xl border border-[#D4AF37]/20 p-2 shadow-xl ${
                        isDark ? 'bg-[#0E0E0E]' : 'bg-[#FFF9EA]'
                      }`}
                    >
                      <div className={`mb-2 px-3 pt-2 text-sm font-semibold ${isDark ? 'text-[#F5EBCD]' : 'text-[#5D4614]'}`}>
                        {language === 'fa' ? 'اعلان‌ها' : 'Notifications'}
                      </div>

                      {hasDegradedSources && (
                        <div className={`mx-2 mb-3 rounded-xl border px-3 py-2 text-xs ${
                          isDark ? 'border-amber-500/35 bg-amber-500/10 text-amber-200' : 'border-amber-400/50 bg-amber-100/90 text-amber-800'
                        }`}>
                          {language === 'fa' ? '⚠️ برخی از منابع تامین قیمت در دسترس نیستند.' : '⚠️ Some pricing providers are down.'}
                        </div>
                      )}

                      <div className="space-y-1">
                        {notifications.map((notif) => (
                          <div
                            key={notif.id}
                            className={`relative flex cursor-pointer flex-col gap-1 rounded-xl p-3 text-sm transition-colors ${
                              isDark ? 'hover:bg-[#171717]' : 'hover:bg-[#F2E4BC]'
                            }`}
                          >
                            {!notif.read && (
                              <span className="absolute start-1.5 top-3.5 h-1.5 w-1.5 rounded-full bg-[#EF4444]" />
                            )}
                            <div className={`font-medium ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'} ${!notif.read ? 'ps-3' : ''}`}>
                              {notif.title[language]}
                            </div>
                            <div className={`text-xs ${isDark ? 'text-[#9C8A5D]' : 'text-[#8A6B20]'} ${!notif.read ? 'ps-3' : ''}`}>
                              {notif.time[language]}
                            </div>
                          </div>
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
                onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                className="flex items-center gap-2 pe-1 cursor-pointer transition-opacity hover:opacity-80"
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
                      transition={{ duration: 0.15 }}
                      className={`absolute ${language === 'fa' ? 'left-0' : 'right-0'} top-full mt-2 z-40 w-48 overflow-hidden rounded-xl border shadow-xl ${
                        isDark
                          ? 'border-white/10 bg-[#1A1A1A]'
                          : 'border-black/10 bg-white'
                      }`}
                    >
                      <div className="p-1">
                        <button
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            setIsUserInfoOpen(true);
                          }}
                          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                            isDark
                              ? 'text-[#E2D3AA] hover:bg-[#252525]'
                              : 'text-[#6E5317] hover:bg-[#F6EBD0]'
                          }`}
                        >
                          <User size={16} />
                          <span>{language === 'fa' ? 'اطلاعات کاربری' : 'User Info'}</span>
                        </button>

                        <button
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            setIsChangePasswordOpen(true);
                          }}
                          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                            isDark
                              ? 'text-[#E2D3AA] hover:bg-[#252525]'
                              : 'text-[#6E5317] hover:bg-[#F6EBD0]'
                          }`}
                        >
                          <KeyRound size={16} />
                          <span>{language === 'fa' ? 'تغییر رمز عبور' : 'Change Password'}</span>
                        </button>

                        <button
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            navigate('/support');
                          }}
                          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
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
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            logout();
                          }}
                          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
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
