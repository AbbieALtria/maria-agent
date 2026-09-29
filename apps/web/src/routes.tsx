import { Navigate, type RouteObject } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { crmRoutes } from "./crm/routes";
import { RequireAuth } from "./lib/auth";
import { LoginPage } from "./pages/Login";

export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/crm" replace /> },
  { path: "/login", element: <LoginPage /> },
  {
    path: "/crm",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: crmRoutes,
  },
  { path: "*", element: <Navigate to="/crm" replace /> },
];
