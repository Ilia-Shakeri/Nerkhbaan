import { Bell, LayoutDashboard, LogOut, Menu, Settings, ShieldAlert } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useState } from "react";
import { useAuthStore } from "@/app/store/authStore";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/alerts", label: "Alerts", icon: ShieldAlert },
  { to: "/settings", label: "Settings", icon: Settings }
];

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const logout = useAuthStore((state) => state.logout);

  // Layout boundaries adjusted to fit viewport seamlessly without the topbar
  return (
    <div className="relative flex min-h-screen flex-col bg-grid">
      <div className="flex flex-1">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 w-72 border-r border-cyan-300/15 bg-slate-950/70 p-4 backdrop-blur-xl transition-transform lg:static lg:translate-x-0",
            sidebarOpen ? "translate-x-0" : "-translate-x-full"
          )}
        >
          <div className="mb-6 rounded-2xl border border-cyan-300/25 bg-slate-900/60 p-4 shadow-neon">
            <p className="text-xs uppercase tracking-[0.28em] text-cyan-300">Nerkhbaan Node</p>
            <h1 className="mt-2 text-xl font-semibold text-cyan-100">Cyber Command</h1>
          </div>

          <nav className="space-y-2">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setSidebarOpen(false)}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-xl border px-4 py-3 text-sm transition",
                    isActive
                      ? "border-cyan-300/35 bg-cyan-400/15 text-cyan-100"
                      : "border-transparent text-cyan-200/90 hover:border-cyan-300/25 hover:bg-slate-900/70"
                  )
                }
              >
                <item.icon size={16} />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>

          <button
            onClick={logout}
            className="mt-6 flex w-full items-center gap-3 rounded-xl border border-cyan-300/25 bg-slate-900/60 px-4 py-3 text-sm text-cyan-100 transition hover:bg-slate-800/80"
          >
            <LogOut size={16} />
            <span>Log out</span>
          </button>
        </aside>

        {sidebarOpen && (
          <button
            aria-label="Close sidebar"
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 z-30 bg-slate-950/70 lg:hidden"
          />
        )}

        <div className="relative flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-cyan-300/15 bg-slate-950/70 px-4 backdrop-blur-xl lg:px-8">
            <button
              onClick={() => setSidebarOpen((value) => !value)}
              className="rounded-lg border border-cyan-300/25 bg-slate-900/70 p-2 text-cyan-200 lg:hidden"
            >
              <Menu size={18} />
            </button>
            <div className="hidden text-xs uppercase tracking-[0.24em] text-cyan-300 lg:block">Private Instance</div>
            <button className="relative rounded-lg border border-cyan-300/25 bg-slate-900/70 p-2 text-cyan-200">
              <Bell size={18} />
              <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-cyan-300" />
            </button>
          </header>

          <main className="flex-1 p-4 lg:p-8">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}