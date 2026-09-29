import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { apiGet } from "../lib/api";

const NAV = [
  { to: "/crm", label: "Dashboard", end: true },
  { to: "/crm/campaigns", label: "Campaigns" },
  { to: "/crm/leads", label: "Leads" },
  { to: "/crm/calls", label: "Calls" },
  { to: "/crm/appointments", label: "Appointments" },
  { to: "/crm/review", label: "Review" },
  { to: "/crm/playbooks", label: "Playbooks" },
  { to: "/crm/settings", label: "Settings" },
];

function ApiStatus() {
  const { data, isError, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<{ ok: boolean }>("/health"),
    refetchInterval: 30_000,
  });
  const label = isLoading ? "checking…" : isError || !data?.ok ? "API offline" : "API online";
  const color = isLoading ? "bg-slate-400" : isError ? "bg-red-500" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </div>
  );
}

export function AppShell() {
  return (
    <div className="flex min-h-screen text-slate-900">
      <aside className="flex w-56 flex-col bg-slate-900 p-4 text-slate-100">
        <div className="mb-6 text-lg font-semibold">Maria CRM</div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded px-3 py-2 text-sm ${isActive ? "bg-slate-700 font-medium" : "hover:bg-slate-800"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <ApiStatus />
      </aside>
      <main className="flex-1 p-8">
        <Outlet />
      </main>
    </div>
  );
}
