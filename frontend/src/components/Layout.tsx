import { NavLink, Outlet } from "react-router-dom";

export default function Layout() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
      isActive ? "bg-gray-900 text-white" : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
    }`;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold tracking-tight text-gray-900">
              Sahaara Score
            </span>
            <span className="text-xs text-gray-400">Reviewer</span>
          </div>
          <nav className="flex gap-1">
            <NavLink to="/" end className={linkClass}>
              Applicants
            </NavLink>
            <NavLink to="/summary" className={linkClass}>
              Summary
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
