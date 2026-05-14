import React, { useState } from 'react';
import { NavLink, Outlet, Navigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import {
  Bell,
  Settings,
  LayoutDashboard,
  BellRing,
  LogOut,
  ChevronDown,
  UserCircle2,
  Menu,
  X
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { WindowTitleBar } from '../components/WindowTitleBar';
import logo from '../../logo/logo.png';

const NAV_ITEMS = [
  { path: '/', label: { fa: 'داشبورد', en: 'Dashboard' }, icon: LayoutDashboard },
  { path: '/alerts', label: { fa: 'هشدارها', en: 'Alerts' }, icon: BellRing },
  { path: '/settings', label: { fa: 'تنظیمات', en: 'Settings' }, icon: Settings },
];

export function DesktopLayout() {
  const { language, theme, logout } = useAppContext();
  const { isAuthenticated } = useAppContext();
  const isDark = theme === 'dark';
  
  if (!isAuthenticated) {
    return <Navigate to="/auth" replace />;
  }
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

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

  const SidebarContent = () => (
    <>
      <div className="flex h-20 items-center justify-center border-b border-[#D4AF37]/15 shrink-0">
        <img
          src={logo}
          alt={language === 'fa' ? 'لوگو نرخ‌بان' : 'Nerkhban logo'}
          className="h-16 w-16 object-contain"
        />
      </div>

      <nav className="flex-1 space-y-2 p-4 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            onClick={() => setIsSidebarOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-all ${
                isActive
                  ? 'bg-[#D4AF37] text-[#0A0A0A] shadow-[0_4px_20px_rgba(212,175,55,0.25)]'
                  : isDark
                    ? 'text-[#CFBE91] hover:bg-[#191919] hover:text-[#F6E8C2]'
                    : 'text-[#8A6B20] hover:bg-[#F6EBD0] hover:text-[#5D4614]'
              }`
            }
          >
            <item.icon size={18} />
            <span>{item.label[language]}</span>
          </NavLink>
        ))}
      </nav>

      <div className="shrink-0 border-t border-[#D4AF37]/15 p-4">
        <button
          onClick={logout}
          className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-colors ${
            isDark ? 'text-[#E6C977] hover:bg-[#1B1B1B]' : 'text-[#86631A] hover:bg-[#F6EBD0]'
          }`}
        >
          <LogOut size={18} />
          <span>{language === 'fa' ? 'خروج از حساب' : 'Logout'}</span>
        </button>
      </div>
    </>
  );

  return (
    <div
      className={`flex h-screen w-full overflow-hidden transition-colors duration-500 ${
        isDark ? 'bg-[#050505] text-[#F2E8CC]' : 'bg-[#FFF8E8] text-[#4A3913]'
      }`}
    >
      <div className="fixed inset-x-0 top-0 z-[70]">
        <WindowTitleBar theme={theme} />
      </div>
      
      {/* Desktop Sidebar */}
      <aside
        className={`mt-10 hidden w-64 flex-col border-e border-[#D4AF37]/15 transition-colors duration-500 lg:flex ${
          isDark ? 'bg-[#0B0B0B]' : 'bg-[#FFF3D8]'
        }`}
      >
        <SidebarContent />
      </aside>

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
            transition={{ type: 'spring', bounce: 0.1, duration: 0.45 }}
            className={`fixed bottom-0 top-10 z-50 flex w-72 flex-col ${
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

      {/* Main Content */}
      <div className="relative mt-10 flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header
          className={`z-10 flex h-16 shrink-0 items-center justify-between border-b border-[#D4AF37]/12 px-6 backdrop-blur-md transition-colors duration-500 ${
            isDark ? 'bg-[#0B0B0B]/95' : 'bg-[#FFF3D8]/95'
          }`}
        >
          <div className="flex items-center gap-4 lg:hidden">
             <button 
                onClick={() => setIsSidebarOpen(true)}
                className={`-mx-2 rounded-lg p-2 ${isDark ? 'text-[#CFBE91] hover:bg-[#171717]' : 'text-[#8A6B20] hover:bg-[#F2E4BC]'}`}
             >
                <Menu size={20} />
             </button>
             <div className="flex items-center gap-2">
               <img
                 src={logo}
                 alt={language === 'fa' ? 'لوگو نرخ‌بان' : 'Nerkhban logo'}
                 className="h-8 w-8 object-contain"
               />
             </div>
          </div>
          
          <div className="hidden lg:block">
            <img
              src={logo}
              alt={language === 'fa' ? 'لوگو نرخ‌بان' : 'Nerkhban logo'}
              className="h-10 w-10 object-contain"
            />
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
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
                      <div className="space-y-1">
                        {notifications.map((notif) => (
                          <div
                            key={notif.id}
                            className={`relative flex cursor-pointer flex-col gap-1 rounded-xl p-3 text-sm transition-colors ${
                              isDark ? 'hover:bg-[#171717]' : 'hover:bg-[#F2E4BC]'
                            }`}
                          >
                            {!notif.read && (
                               <div className="absolute top-4 start-1.5 h-1.5 w-1.5 rounded-full bg-[#10B981]" />
                            )}
                            <span className={`ps-2 ${isDark ? 'text-[#E8DBB5]' : 'text-[#5D4614]'} ${!notif.read ? 'font-medium' : ''}`}>
                              {notif.title[language]}
                            </span>
                            <span className={`ps-2 text-xs ${isDark ? 'text-[#A89668]' : 'text-[#8A6B20]'}`}>
                              {notif.time[language]}
                            </span>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  </>
                )}
              </AnimatePresence>
            </div>

            {/* User Profile Mini */}
            <div
              className={`flex cursor-pointer items-center gap-2 rounded-xl border border-[#D4AF37]/18 p-1.5 pe-3 transition-colors ${
                isDark ? 'hover:bg-[#171717]' : 'hover:bg-[#F2E4BC]'
              }`}
            >
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#D4AF37] text-[#0A0A0A]">
                <UserCircle2 size={16} />
              </div>
              <span className={`hidden text-sm font-medium sm:block ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
                {language === 'fa' ? 'کاربر دمو' : 'Demo User'}
              </span>
              <ChevronDown size={14} className={`hidden sm:block ${isDark ? 'text-[#9C8A5D]' : 'text-[#8A6B20]'}`} />
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className={`flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 ${isDark ? 'bg-[#050505]' : 'bg-[#FFF8E8]'}`}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
