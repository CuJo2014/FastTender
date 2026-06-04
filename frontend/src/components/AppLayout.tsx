import { NavLink, Outlet } from "react-router-dom";
import { clsx } from "clsx";

const NAV_ITEMS = [
  { to: "/specifications", label: "Спецификации" },
  { to: "/catalog", label: "Каталог" },
  { to: "/suppliers", label: "Поставщики" },
  { to: "/clients", label: "Клиенты" },
];

export function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 h-14 border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-full max-w-7xl items-center gap-8 px-6">
          <div className="text-lg font-semibold tracking-tight">FastTender</div>
          <nav className="flex gap-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium",
                    isActive
                      ? "bg-slate-900 text-white"
                      : "text-slate-700 hover:bg-slate-100",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto text-xs text-slate-400">
            Phase 1 — прототип
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
