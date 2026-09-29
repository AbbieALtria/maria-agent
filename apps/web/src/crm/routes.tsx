import type { RouteObject } from "react-router-dom";
import { CampaignEditor } from "./campaigns/CampaignEditor";
import { CampaignsPage } from "./campaigns/CampaignsPage";
import { LeadsPage } from "./leads/LeadsPage";
import { Placeholder } from "./Placeholder";
import { SettingsPage } from "./settings/SettingsPage";

const PLACEHOLDERS = [
  ["calls", "Calls"],
  ["appointments", "Appointments"],
  ["review", "Review"],
  ["playbooks", "Playbooks"],
] as const;

export const crmRoutes: RouteObject[] = [
  { index: true, element: <Placeholder title="Dashboard" /> },
  { path: "campaigns", element: <CampaignsPage /> },
  { path: "campaigns/new", element: <CampaignEditor /> },
  { path: "campaigns/:id", element: <CampaignEditor key="edit" /> },
  { path: "leads", element: <LeadsPage /> },
  { path: "settings", element: <SettingsPage /> },
  ...PLACEHOLDERS.map(([path, title]) => ({ path, element: <Placeholder title={title} /> })),
];
