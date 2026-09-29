import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Checkbox,
  ErrorText,
  Field,
  Input,
  PageHeader,
  Select,
  Tabs,
  Textarea,
} from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { TIMEZONES } from "../../lib/format";
import { useClients, useTeams, useTrunks } from "../../lib/queries";
import type {
  AppointmentSettings,
  Campaign,
  CallingWindow,
  ComplianceSettings,
  Market,
} from "../../lib/types";
import { PlaybookTab } from "./PlaybookTab";

const TABS = [
  { key: "general", label: "General" },
  { key: "telephony", label: "Telephony" },
  { key: "schedule", label: "Schedule & Pacing" },
  { key: "appointments", label: "Appointments" },
  { key: "compliance", label: "Compliance" },
  { key: "playbook", label: "Playbook" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

export type Draft = Omit<
  Campaign,
  | "id"
  | "status"
  | "active_playbook_version_id"
  | "created_at"
  | "updated_at"
  | "lead_counts"
  | "daily_budget_usd"
> & { daily_budget_usd: string };

const MARKET_DEFAULTS: Record<Market, { tz: string; countries: string[]; languages: string[] }> = {
  US: { tz: "America/New_York", countries: ["US"], languages: ["en"] },
  CA: { tz: "America/Toronto", countries: ["CA"], languages: ["en"] },
  PH: { tz: "Asia/Manila", countries: ["PH"], languages: ["en", "fil"] },
  OTHER: { tz: "UTC", countries: [], languages: ["en"] },
};

function emptyDraft(): Draft {
  return {
    name: "",
    client_id: "",
    market: "US",
    country_codes: ["US"],
    default_timezone: "America/New_York",
    languages: ["en"],
    sip_trunk_id: null,
    caller_id: null,
    calling_window: Object.fromEntries(
      DAYS.slice(0, 5).map((d) => [d, [["09:00", "17:30"]]]),
    ) as CallingWindow,
    max_attempts: 3,
    retry_spacing_hours: 4,
    voicemail_counts_as_attempt: false,
    concurrency: 2,
    daily_cap: null,
    daily_budget_usd: "",
    test_mode: true,
    test_allowlist: [],
    requeue_no_show: false,
    appointment_settings: {
      type: "phone",
      duration_min: 20,
      team_id: null,
      buffer_min: 0,
      lead_time_hours: 24,
      max_days_ahead: 10,
    },
    compliance: {
      ai_disclosure: "on_ask",
      ai_disclosure_text: "",
      recording_notice: false,
      recording_notice_text: "",
      dnc_scrub: true,
    },
  };
}

function toDraft(c: Campaign): Draft {
  const d = emptyDraft();
  return {
    ...d,
    ...Object.fromEntries(Object.keys(d).map((k) => [k, c[k as keyof Campaign]])),
    daily_budget_usd: c.daily_budget_usd ?? "",
    appointment_settings: { ...d.appointment_settings, ...c.appointment_settings },
    compliance: { ...d.compliance, ...c.compliance },
  } as Draft;
}

function toPayload(d: Draft) {
  return {
    ...d,
    sip_trunk_id: d.sip_trunk_id || null,
    caller_id: d.caller_id || null,
    daily_budget_usd: d.daily_budget_usd === "" ? null : d.daily_budget_usd,
    compliance: {
      ...d.compliance,
      ai_disclosure_text: d.compliance.ai_disclosure_text || null,
      recording_notice_text: d.compliance.recording_notice_text || null,
    },
  };
}

const csv = (xs: string[]) => xs.join(", ");
const parseList = (s: string) =>
  s
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);

function numOrNull(v: string): number | null {
  return v === "" ? null : Number(v);
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid max-w-3xl grid-cols-1 gap-4 md:grid-cols-2">{children}</div>;
}

export function CampaignEditor() {
  const { id } = useParams();
  const campaign = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => api.get<Campaign>(`/api/v1/campaigns/${id}`),
    enabled: !!id,
  });
  if (id && campaign.isLoading) return <div className="text-slate-500">Loading…</div>;
  if (id && campaign.error) return <ErrorText error={campaign.error} />;
  return <CampaignForm key={id ?? "new"} campaign={id ? campaign.data : undefined} />;
}

function CampaignForm({ campaign: c }: { campaign?: Campaign }) {
  const id = c?.id;
  const isNew = !c;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { can } = useAuth();
  const editable = can("admin", "manager");
  const [tab, setTab] = useState<TabKey>("general");
  const [draft, setDraft] = useState<Draft>(() => (c ? toDraft(c) : emptyDraft()));
  const [saved, setSaved] = useState(false);

  const clients = useClients();
  const trunks = useTrunks(can("admin", "manager"));
  const teams = useTeams();
  // New campaigns default to the first client until one is picked.
  const clientId = draft.client_id || clients.data?.[0]?.id || "";

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [key]: value }));
  };
  const setAppt = <K extends keyof AppointmentSettings>(k: K, v: AppointmentSettings[K]) =>
    set("appointment_settings", { ...draft.appointment_settings, [k]: v });
  const setComp = <K extends keyof ComplianceSettings>(k: K, v: ComplianceSettings[K]) =>
    set("compliance", { ...draft.compliance, [k]: v });

  const save = useMutation({
    mutationFn: () =>
      isNew
        ? api.post<Campaign>("/api/v1/campaigns", toPayload({ ...draft, client_id: clientId }))
        : api.patch<Campaign>(`/api/v1/campaigns/${id}`, toPayload(draft)),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      qc.setQueryData(["campaign", saved.id], saved);
      setDraft(toDraft(saved)); // pick up server-side normalization (E.164 etc.)
      setSaved(true);
      if (isNew) navigate(`/crm/campaigns/${saved.id}`, { replace: true });
    },
  });

  const action = useMutation({
    mutationFn: (a: string) => api.post<Campaign>(`/api/v1/campaigns/${id}/actions/${a}`),
    onSuccess: (updated, a) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      if (a === "clone") navigate(`/crm/campaigns/${updated.id}`);
      else qc.setQueryData(["campaign", updated.id], updated);
    },
  });

  const newClient = useMutation({
    mutationFn: (name: string) => api.post<{ id: string }>("/api/v1/clients", { name }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      set("client_id", c.id);
    },
  });

  const trunk = trunks.data?.find((t) => t.id === draft.sip_trunk_id);
  const readOnly = !editable || c?.status === "completed";

  return (
    <div>
      <PageHeader
        title={isNew ? "New campaign" : c?.name ?? ""}
        actions={
          <>
            {c && <Badge value={c.status} />}
            {c && editable && (
              <>
                {(c.status === "draft" || c.status === "testing") && (
                  <Button
                    variant="secondary"
                    onClick={() => action.mutate("start")}
                    disabled={c.status === "testing" && c.test_mode}
                  >
                    Start
                  </Button>
                )}
                {(c.status === "testing" || c.status === "active") && (
                  <Button variant="secondary" onClick={() => action.mutate("pause")}>
                    Pause
                  </Button>
                )}
                {c.status === "paused" && (
                  <Button variant="secondary" onClick={() => action.mutate("resume")}>
                    Resume
                  </Button>
                )}
                <Button variant="secondary" onClick={() => action.mutate("clone")}>
                  Clone
                </Button>
                {c.status !== "completed" && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      if (confirm("Complete (archive) this campaign? It becomes read-only."))
                        action.mutate("complete");
                    }}
                  >
                    Complete
                  </Button>
                )}
              </>
            )}
          </>
        }
      />

      {draft.test_mode && (
        <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          <strong>Test mode.</strong> Only numbers in the test allowlist can be dialed
          {draft.test_allowlist.length
            ? ` (${draft.test_allowlist.length} number${draft.test_allowlist.length > 1 ? "s" : ""}).`
            : " — the allowlist is empty, so nothing will be dialed."}
        </div>
      )}
      <div className="mb-4 space-y-2">
        <ErrorText error={action.error} />
      </div>

      <Tabs tabs={isNew ? TABS.slice(0, 5) : TABS} value={tab} onChange={setTab} />

      {tab === "playbook" && c ? (
        <PlaybookTab campaign={c} editable={editable} />
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <fieldset disabled={readOnly} className="space-y-4">
            {tab === "general" && (
              <Grid>
                <Field label="Name" className="md:col-span-2">
                  <Input value={draft.name} onChange={(e) => set("name", e.target.value)} required />
                </Field>
                <Field label="Client">
                  <div className="flex gap-2">
                    <Select
                      aria-label="Client"
                      value={clientId}
                      onChange={(e) => set("client_id", e.target.value)}
                      required
                    >
                      <option value="">Select…</option>
                      {clients.data?.map((cl) => (
                        <option key={cl.id} value={cl.id}>
                          {cl.name}
                        </option>
                      ))}
                    </Select>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        const name = prompt("New client name");
                        if (name?.trim()) newClient.mutate(name.trim());
                      }}
                    >
                      +
                    </Button>
                  </div>
                </Field>
                <Field label="Market">
                  <Select
                    value={draft.market}
                    onChange={(e) => {
                      const m = e.target.value as Market;
                      const d = MARKET_DEFAULTS[m];
                      setDraft((x) => ({
                        ...x,
                        market: m,
                        default_timezone: isNew ? d.tz : x.default_timezone,
                        country_codes: isNew ? d.countries : x.country_codes,
                        languages: isNew ? d.languages : x.languages,
                      }));
                    }}
                  >
                    {(["US", "CA", "PH", "OTHER"] as Market[]).map((m) => (
                      <option key={m}>{m}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Country codes" hint="ISO codes, first one is the default for phone parsing">
                  <Input
                    value={csv(draft.country_codes)}
                    onChange={(e) => set("country_codes", parseList(e.target.value.toUpperCase()))}
                  />
                </Field>
                <Field label="Default timezone" hint="Used when a lead's timezone can't be inferred">
                  <Select
                    value={draft.default_timezone}
                    onChange={(e) => set("default_timezone", e.target.value)}
                  >
                    {TIMEZONES.map((tz) => (
                      <option key={tz}>{tz}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Languages" hint="e.g. en, fil">
                  <Input
                    value={csv(draft.languages)}
                    onChange={(e) => set("languages", parseList(e.target.value))}
                  />
                </Field>
              </Grid>
            )}

            {tab === "telephony" && (
              <Grid>
                <Field label="SIP trunk">
                  <Select
                    value={draft.sip_trunk_id ?? ""}
                    onChange={(e) => {
                      setDraft((d) => ({ ...d, sip_trunk_id: e.target.value || null, caller_id: null }));
                    }}
                  >
                    <option value="">None</option>
                    {trunks.data?.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name} ({t.market}){t.is_active ? "" : " — inactive"}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Caller ID" hint={trunk && !trunk.caller_ids.length ? "This trunk has no caller IDs yet (Settings → SIP trunks)." : undefined}>
                  <Select
                    value={draft.caller_id ?? ""}
                    onChange={(e) => set("caller_id", e.target.value || null)}
                    disabled={!trunk}
                  >
                    <option value="">None</option>
                    {trunk?.caller_ids.map((n) => (
                      <option key={n}>{n}</option>
                    ))}
                  </Select>
                </Field>
                <div className="md:col-span-2">
                  <Checkbox
                    label="Test mode — dial only allowlisted numbers"
                    checked={draft.test_mode}
                    onChange={(v) => set("test_mode", v)}
                  />
                </div>
                <Field
                  label="Test allowlist"
                  hint="One number per line; normalized to E.164 on save"
                  className="md:col-span-2"
                >
                  <Textarea
                    rows={4}
                    value={draft.test_allowlist.join("\n")}
                    onChange={(e) => set("test_allowlist", e.target.value.split("\n"))}
                    onBlur={(e) => set("test_allowlist", parseList(e.target.value))}
                  />
                </Field>
              </Grid>
            )}

            {tab === "schedule" && (
              <div className="space-y-6">
                <div>
                  <h3 className="mb-2 text-sm font-medium">
                    Calling window (prospect-local time, within 08:00–21:00)
                  </h3>
                  <CallingWindowEditor
                    value={draft.calling_window}
                    onChange={(v) => set("calling_window", v)}
                  />
                </div>
                <Grid>
                  <Field label="Max attempts">
                    <Input type="number" min={1} max={20} value={draft.max_attempts}
                      onChange={(e) => set("max_attempts", Number(e.target.value))} />
                  </Field>
                  <Field label="Retry spacing (hours)">
                    <Input type="number" min={0} value={draft.retry_spacing_hours}
                      onChange={(e) => set("retry_spacing_hours", Number(e.target.value))} />
                  </Field>
                  <Field label="Concurrency" hint="Simultaneous calls (1–20)">
                    <Input type="number" min={1} max={20} value={draft.concurrency}
                      onChange={(e) => set("concurrency", Number(e.target.value))} />
                  </Field>
                  <Field label="Daily cap (dials)" hint="Blank = no cap">
                    <Input type="number" min={0} value={draft.daily_cap ?? ""}
                      onChange={(e) => set("daily_cap", numOrNull(e.target.value))} />
                  </Field>
                  <Field label="Daily budget (USD)" hint="Blank = no budget">
                    <Input type="number" min={0} step="0.01" value={draft.daily_budget_usd}
                      onChange={(e) => set("daily_budget_usd", e.target.value)} />
                  </Field>
                  <div className="flex items-end">
                    <Checkbox label="Voicemail counts as an attempt"
                      checked={draft.voicemail_counts_as_attempt}
                      onChange={(v) => set("voicemail_counts_as_attempt", v)} />
                  </div>
                </Grid>
              </div>
            )}

            {tab === "appointments" && (
              <Grid>
                <Field label="Type">
                  <Select value={draft.appointment_settings.type}
                    onChange={(e) => setAppt("type", e.target.value as AppointmentSettings["type"])}>
                    <option value="phone">Phone</option>
                    <option value="video">Video</option>
                    <option value="onsite">On-site</option>
                  </Select>
                </Field>
                <Field label="Team">
                  <Select value={draft.appointment_settings.team_id ?? ""}
                    onChange={(e) => setAppt("team_id", e.target.value || null)}>
                    <option value="">None</option>
                    {teams.data?.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Duration (min)">
                  <Input type="number" min={5} value={draft.appointment_settings.duration_min}
                    onChange={(e) => setAppt("duration_min", Number(e.target.value))} />
                </Field>
                <Field label="Buffer between appointments (min)">
                  <Input type="number" min={0} value={draft.appointment_settings.buffer_min}
                    onChange={(e) => setAppt("buffer_min", Number(e.target.value))} />
                </Field>
                <Field label="Minimum lead time (hours)">
                  <Input type="number" min={0} value={draft.appointment_settings.lead_time_hours}
                    onChange={(e) => setAppt("lead_time_hours", Number(e.target.value))} />
                </Field>
                <Field label="Book up to (days ahead)">
                  <Input type="number" min={1} value={draft.appointment_settings.max_days_ahead}
                    onChange={(e) => setAppt("max_days_ahead", Number(e.target.value))} />
                </Field>
                <div className="md:col-span-2">
                  <Checkbox label="Requeue lead as callback when the appointment is a no-show"
                    checked={draft.requeue_no_show} onChange={(v) => set("requeue_no_show", v)} />
                </div>
              </Grid>
            )}

            {tab === "compliance" && (
              <Grid>
                <Field label="AI disclosure">
                  <Select value={draft.compliance.ai_disclosure}
                    onChange={(e) => setComp("ai_disclosure", e.target.value as ComplianceSettings["ai_disclosure"])}>
                    <option value="on_ask">When asked</option>
                    <option value="upfront">Up front</option>
                  </Select>
                </Field>
                <div className="flex items-end">
                  <Checkbox label="Scrub against DNC before every dial" checked={draft.compliance.dnc_scrub}
                    onChange={(v) => setComp("dnc_scrub", v)} />
                </div>
                <Field label="AI disclosure text" hint="What Maria says when asked if she is an AI" className="md:col-span-2">
                  <Textarea rows={3} value={draft.compliance.ai_disclosure_text ?? ""}
                    onChange={(e) => setComp("ai_disclosure_text", e.target.value)} />
                </Field>
                <div className="md:col-span-2">
                  <Checkbox label="Play a recording notice at the start of the call"
                    checked={draft.compliance.recording_notice}
                    onChange={(v) => setComp("recording_notice", v)} />
                </div>
                <Field label="Recording notice text" className="md:col-span-2">
                  <Textarea rows={2} value={draft.compliance.recording_notice_text ?? ""}
                    onChange={(e) => setComp("recording_notice_text", e.target.value)} />
                </Field>
              </Grid>
            )}

            <ErrorText error={save.error} />
            {!readOnly && (
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={save.isPending}>
                  {save.isPending ? "Saving…" : isNew ? "Create campaign" : "Save changes"}
                </Button>
                <Link to="/crm/campaigns" className="text-sm text-slate-500">Cancel</Link>
                {saved && <span className="text-sm text-emerald-700">Saved</span>}
              </div>
            )}
          </fieldset>
        </form>
      )}
    </div>
  );
}

function CallingWindowEditor({
  value,
  onChange,
}: {
  value: CallingWindow;
  onChange: (v: CallingWindow) => void;
}) {
  const update = (day: string, ranges: [string, string][]) => {
    const next = { ...value };
    if (ranges.length) next[day] = ranges;
    else delete next[day];
    onChange(next);
  };
  return (
    <div className="max-w-xl space-y-2">
      {DAYS.map((day) => {
        const ranges = value[day] ?? [];
        return (
          <div key={day} className="flex items-start gap-3">
            <label className="flex w-20 items-center gap-2 pt-1.5 text-sm capitalize">
              <input
                type="checkbox"
                checked={ranges.length > 0}
                onChange={(e) => update(day, e.target.checked ? [["09:00", "17:30"]] : [])}
              />
              {day}
            </label>
            <div className="flex flex-1 flex-col gap-1">
              {ranges.map(([start, end], i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input type="time" min="08:00" max="21:00" value={start} className="w-32"
                    aria-label={`${day} start ${i + 1}`}
                    onChange={(e) => update(day, ranges.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} />
                  <span className="text-slate-400">–</span>
                  <Input type="time" min="08:00" max="21:00" value={end} className="w-32"
                    aria-label={`${day} end ${i + 1}`}
                    onChange={(e) => update(day, ranges.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} />
                  <Button variant="ghost" onClick={() => update(day, ranges.filter((_, j) => j !== i))}>
                    Remove
                  </Button>
                </div>
              ))}
              {ranges.length > 0 && (
                <button type="button" className="self-start text-xs text-indigo-700"
                  onClick={() => update(day, [...ranges, ["13:00", "17:00"]])}>
                  + add range
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
