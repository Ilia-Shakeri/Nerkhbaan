import React, { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router';
import { motion, AnimatePresence } from 'motion/react';
import {
  Bell,
  Settings,
  LayoutDashboard,
  BellRing,
  LogOut,
  ChevronDown,
  Activity,
  UserCircle2,
  Menu,
  X
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';

const NAV_ITEMS = [
  { path: '/', label: { fa: 'داشبورد', en: 'Dashboard' }, icon: LayoutDashboard },
  { path: '/alerts', label: { fa: 'هشدارها', en: 'Alerts' }, icon: BellRing },
  { path: '/settings', label: { fa: 'تنظیمات', en: 'Settings' }, icon: Settings },
];

export function DesktopLayout() {
  const { language, theme, logout } = useAppContext();
  const location = useLocation();
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const notifications = [
    { id: 1, title: 'قیمت طلا به حد مورد نظر رسید 🔔', time: '۱۰ دقیقه پیش', read: false },
    { id: 2, title: 'بیت‌کوین از ۶۵,۰۰۰ عبور کرد 🚀', time: '۱ ساعت پیش', read: true },
  ];

  const SidebarContent = () => (
    <>
      <div className="flex h-16 items-center px-6 gap-3 border-b border-slate-200 dark:border-white/5 shrink-0">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#D4AF37] text-[#0A0A0A] shadow-[0_2px_10px_0_rgba(212,175,55,0.3)]">
          <Activity size={18} strokeWidth={2.5} />
        </div>
        <span className="text-xl font-bold tracking-tight text-[#0B1F3A] dark:text-white">
          {language === 'fa' ? 'نرخ‌بان' : 'Rateban'}
        </span>
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
                  ? 'bg-[#0B1F3A] text-white dark:bg-white/10 dark:text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-white/5 dark:hover:text-white'
              }`
            }
          >
            <item.icon size={18} />
            <span>{item.label[language]}</span>
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-slate-200 dark:border-white/5 shrink-0">
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-500/10"
        >
          <LogOut size={18} />
          <span>{language === 'fa' ? 'خروج از حساب' : 'Logout'}</span>
        </button>
      </div>
    </>
  );

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[#F8FAFC] dark:bg-[#0A0A0A] text-slate-900 dark:text-white transition-colors duration-300">
      
      {/* Desktop Sidebar */}
      <aside className="hidden w-64 flex-col border-e border-slate-200 bg-white dark:border-white/5 dark:bg-[#121212] lg:flex transition-colors duration-300">
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
            transition={{ type: 'spring', bounce: 0, duration: 0.3 }}
            className={`fixed top-0 bottom-0 z-50 flex w-72 flex-col bg-white dark:bg-[#121212] lg:hidden ${
              language === 'fa' ? 'right-0 border-l border-white/5' : 'left-0 border-r border-white/5'
            }`}
          >
            <button 
              onClick={() => setIsSidebarOpen(false)}
              className="absolute top-4 end-4 p-2 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
            >
              <X size={20} />
            </button>
            <SidebarContent />
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden relative">
        {/* Topbar */}
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white/50 px-6 backdrop-blur-md dark:border-white/5 dark:bg-[#121212]/50 z-10">
          <div className="flex items-center gap-4 lg:hidden">
             <button 
                onClick={() => setIsSidebarOpen(true)}
                className="p-2 -mx-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-white/5"
             >
                <Menu size={20} />
             </button>
             <span className="font-bold tracking-tight">{language === 'fa' ? 'نرخ‌بان' : 'Rateban'}</span>
          </div>
          
          <div className="hidden lg:block">
            <h1 className="text-xl font-semibold text-[#0B1F3A] dark:text-white capitalize tracking-tight">
               {NAV_ITEMS.find((n) => n.path === location.pathname)?.label[language] || ''}
            </h1>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            {/* Notification Bell */}
            <div className="relative">
              <button
                onClick={() => setIsNotificationsOpen(!isNotificationsOpen)}
                className="relative flex h-10 w-10 items-center justify-center rounded-xl text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/10"
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
                       onClick={() => setIsNotificationsOpen(false)}
                       className="fixed inset-0 z-10" 
                    />
                    <motion.div
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      className="absolute end-0 top-12 z-20 w-80 rounded-2xl border border-slate-200 bg-white p-2 shadow-xl dark:border-white/10 dark:bg-[#121212]"
                    >
                      <div className="mb-2 px-3 pt-2 text-sm font-semibold text-slate-900 dark:text-white">
                        {language === 'fa' ? 'اعلان‌ها' : 'Notifications'}
                      </div>
                      <div className="space-y-1">
                        {notifications.map((notif) => (
                          <div
                            key={notif.id}
                            className="flex flex-col gap-1 rounded-xl p-3 text-sm transition-colors hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer relative"
                          >
                            {!notif.read && (
                               <div className="absolute top-4 start-1.5 h-1.5 w-1.5 rounded-full bg-[#10B981]" />
                            )}
                            <span className={`ps-2 text-slate-800 dark:text-slate-200 ${!notif.read ? 'font-medium' : ''}`}>
                              {notif.title}
                            </span>
                            <span className="ps-2 text-xs text-slate-500 dark:text-slate-400">
                              {notif.time}
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
            <div className="flex cursor-pointer items-center gap-2 rounded-xl border border-slate-200 p-1.5 pe-3 transition-colors hover:bg-slate-50 dark:border-white/10 dark:hover:bg-white/5">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#0B1F3A] text-[#D4AF37] dark:bg-white/10 dark:text-white">
                <UserCircle2 size={16} />
              </div>
              <span className="hidden sm:block text-sm font-medium text-slate-700 dark:text-slate-300">
                {language === 'fa' ? 'کاربر دمو' : 'Demo User'}
              </span>
              <ChevronDown size={14} className="hidden sm:block text-slate-400" />
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
