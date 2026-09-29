import type { RouteObject } from "react-router-dom";
import { Placeholder } from "./Placeholder";

const PAGES = [
  ["campaigns", "Campaigns"],
  ["leads", "Leads"],
  ["calls", "Calls"],
  ["appointments", "Appointments"],
  ["review", "Review"],
  ["playbooks", "Playbooks"],
  ["settings", "Settings"],
] as const;

export const crmRoutes: RouteObject[] = [
  { index: true, element: <Placeholder title="Dashboard" /> },
  ...PAGES.map(([path, title]) => ({ path, element: <Placeholder title={title} /> })),
];
