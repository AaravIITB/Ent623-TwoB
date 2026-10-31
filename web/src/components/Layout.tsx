import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { ROLE_LABEL, useAuth, useUser } from "../lib/auth";
import { cx } from "../lib/format";
import { IconClients, IconHome, IconSignOut, IconUsers } from "./icons";

export function Brand({ className }: { className?: string }) {
  return (
    <div className={cx("flex items-center gap-2", className)}>
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="6" fill="#1E4F8A" />
        <path d="M9 10h14M16 10v13M11 16h6" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" />
      </svg>
      <span className="text-[17px] font-semibold tracking-[-0.01em] text-ink">TaxMind</span>
    </div>
  );
}

export default function Layout() {
  const user = useUser();
  const { logout } = useAuth();
  const nav = useNavigate();
  const items = [
    { to: "/", label: "Dashboard", icon: IconHome, end: true },
    { to: "/clients", label: "Clients", icon: IconClients, end: false },
    ...(user.role === "admin" ? [{ to: "/users", label: "Users", icon: IconUsers, end: false }] : []),
  ];
  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      <header className="md:hidden flex items-center gap-3 h-12 px-3 bg-surface border-b border-rule">
        <Brand />
        <nav className="flex gap-1 ml-auto" aria-label="Main">
          {items.map((it) => (
            <NavLink key={it.to} to={it.to} end={it.end} className={({ isActive }) => cx("h-8 px-2 rounded-md text-sm inline-flex items-center", isActive ? "bg-accent-soft text-accent" : "text-ink-2")}>
              {it.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <aside className="hidden md:flex w-[188px] shrink-0 bg-surface border-r border-rule flex-col sticky top-0 h-screen">
        <div className="h-14 flex items-center px-4 border-b border-rule">
          <Brand />
        </div>
        <nav className="p-2 flex-1 space-y-0.5" aria-label="Main">
          {items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.end}
              className={({ isActive }) =>
                cx(
                  "flex items-center gap-2.5 h-8 px-2.5 rounded-md text-base",
                  isActive ? "bg-accent-soft text-accent font-medium" : "text-ink-2 hover:bg-sunken",
                )
              }
            >
              <it.icon />
              {it.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-rule p-3">
          <div className="text-sm font-medium text-ink truncate">{user.name}</div>
          <div className="text-xs text-muted">{ROLE_LABEL[user.role]}</div>
          <button
            type="button"
            onClick={async () => {
              await logout();
              nav("/login");
            }}
            className="mt-2 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"
          >
            <IconSignOut size={14} /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 min-w-0">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, children }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <header className="px-6 pt-5 pb-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-[-0.015em] text-ink">{title}</h1>
          {subtitle && <div className="mt-0.5 text-sm text-muted">{subtitle}</div>}
        </div>
        {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
      </div>
      {children}
    </header>
  );
}
