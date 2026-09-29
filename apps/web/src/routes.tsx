import { Navigate, type RouteObject } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { crmRoutes } from "./crm/routes";

export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/crm" replace /> },
  { path: "/crm", element: <AppShell />, children: crmRoutes },
  { path: "*", element: <Navigate to="/crm" replace /> },
];
