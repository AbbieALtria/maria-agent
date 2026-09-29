export type Role = "admin" | "manager" | "rep" | "qa";
export type Market = "US" | "CA" | "PH" | "OTHER";
export type CampaignStatus = "draft" | "testing" | "active" | "paused" | "completed";
export type LeadStatus =
  | "new"
  | "queued"
  | "calling"
  | "contacted"
  | "callback"
  | "appointment_set"
  | "not_interested"
  | "wrong_number"
  | "dnc"
  | "exhausted"
  | "invalid"
  | "paused";

export const LEAD_STATUSES: LeadStatus[] = [
  "new",
  "queued",
  "calling",
  "contacted",
  "callback",
  "appointment_set",
  "not_interested",
  "wrong_number",
  "dnc",
  "exhausted",
  "invalid",
  "paused",
];

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  client_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Client {
  id: string;
  name: string;
  contact_email: string | null;
  notes: string | null;
  is_active: boolean;
}

export interface SipTrunk {
  id: string;
  name: string;
  market: Market;
  livekit_trunk_id: string | null;
  provider: string | null;
  caller_ids: string[];
  is_active: boolean;
}

export interface Team {
  id: string;
  name: string;
  client_id: string | null;
  notify_emails: string[];
  webhook_url: string | null;
  timezone: string;
  member_ids: string[];
}

export type CallingWindow = Record<string, [string, string][]>;

export interface ComplianceSettings {
  ai_disclosure: "on_ask" | "upfront";
  ai_disclosure_text: string | null;
  recording_notice: boolean;
  recording_notice_text: string | null;
  dnc_scrub: boolean;
}

export interface AppointmentSettings {
  type: "phone" | "video" | "onsite";
  duration_min: number;
  team_id: string | null;
  buffer_min: number;
  lead_time_hours: number;
  max_days_ahead: number;
}

export interface Campaign {
  id: string;
  client_id: string;
  name: string;
  status: CampaignStatus;
  market: Market;
  country_codes: string[];
  default_timezone: string;
  languages: string[];
  sip_trunk_id: string | null;
  caller_id: string | null;
  calling_window: CallingWindow;
  max_attempts: number;
  retry_spacing_hours: number;
  voicemail_counts_as_attempt: boolean;
  concurrency: number;
  daily_cap: number | null;
  daily_budget_usd: string | null;
  test_mode: boolean;
  test_allowlist: string[];
  requeue_no_show: boolean;
  appointment_settings: AppointmentSettings;
  compliance: ComplianceSettings;
  active_playbook_version_id: string | null;
  created_at: string;
  updated_at: string;
  lead_counts: Record<string, number>;
}

export interface PlaybookVersion {
  id: string;
  campaign_id: string;
  version: number;
  playbook: Record<string, unknown>;
  notes: string | null;
  source: string;
  is_active: boolean;
  created_at: string;
}

export interface Lead {
  id: string;
  campaign_id: string;
  external_id: string | null;
  source: string;
  business_name: string | null;
  contact_name: string | null;
  contact_title: string | null;
  phone_e164: string;
  phone_alt_e164: string | null;
  email: string | null;
  address_line: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country_code: string | null;
  timezone: string | null;
  website: string | null;
  industry: string | null;
  custom: Record<string, unknown>;
  status: LeadStatus;
  attempts: number;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  last_disposition: string | null;
  priority: number;
  notes: string | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ImportIssue {
  row: number;
  reason: "invalid" | "duplicate" | "dnc";
  detail: string;
  value: string | null;
}

export interface ImportReport {
  import_id: string | null;
  dry_run: boolean;
  filename: string | null;
  headers: string[];
  column_map: Record<string, string>;
  suggested_column_map: Record<string, string>;
  row_count: number;
  imported: number;
  skipped_dupe: number;
  skipped_dnc: number;
  skipped_invalid: number;
  issues: ImportIssue[];
  preview: (Record<string, string | number | null> & { row: number; status: string })[];
}

export interface TimelineItem {
  ts: string;
  kind: string;
  title: string;
  data: Record<string, unknown>;
}

export interface DncEntry {
  id: string;
  phone_e164: string;
  scope: "global" | "client";
  client_id: string | null;
  reason: string | null;
  source: string | null;
  created_at: string;
}

export interface BulkResult {
  action: string;
  updated: number;
  skipped: { id: string; reason: string }[];
}
