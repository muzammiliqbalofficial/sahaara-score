import { NavLink, Outlet } from "react-router-dom";
import {
  ClipboardList, FileEdit, SlidersHorizontal, BarChart3, Shield,
} from "lucide-react";

const NAV_ITEMS = [
  { to: "/", label: "Reviewer Queue", icon: ClipboardList, end: true },
  { to: "/apply", label: "Citizen Intake", icon: FileEdit, end: false },
  { to: "/simulator", label: "Judge Simulator", icon: SlidersHorizontal, end: false },
  { to: "/summary", label: "Analytics", icon: BarChart3, end: false },
];

export default function Layout() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-all ${
      isActive
        ? "bg-blue-600 text-white shadow-md shadow-blue-200"
        : "text-gray-500 hover:text-gray-800 hover:bg-white/60"
    }`;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/30 to-slate-100">
      <header className="glass-nav sticky top-0 z-50">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-2.5">
          {/* Brand */}
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
              <Shield className="h-4 w-4 text-white" />
            </div>
            <div>
              <span className="text-sm font-bold tracking-tight text-gray-900">
                Sahaara Score
              </span>
              <span className="ml-1.5 text-[10px] font-medium text-gray-400">
                v2.0
              </span>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex gap-0.5">
            {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={linkClass}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </NavLink>
            ))}
          </nav>

          {/* Alibaba Cloud badge */}
          <div className="flex items-center gap-1.5 rounded-full bg-gradient-to-r from-orange-50 to-amber-50 px-3 py-1 ring-1 ring-orange-200/60">
            <div className="h-1.5 w-1.5 rounded-full bg-orange-500 animate-pulse" />
            <span className="text-[10px] font-semibold text-orange-700">
              Powered by Alibaba Cloud AI
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-gray-200/50 bg-white/30 py-3 text-center text-[10px] text-gray-400">
        Sahaara Score &copy; {new Date().getFullYear()} — Fair, Transparent, AI-Powered Eligibility Assessment
      </footer>
    </div>
  );
}
