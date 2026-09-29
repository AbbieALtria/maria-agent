import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Drawer, ErrorText, Field, Input, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { dateTime, localTime } from "../../lib/format";
import type { Lead, TimelineItem } from "../../lib/types";

const EDITABLE = [
  ["business_name", "Business"],
  ["contact_name", "Contact"],
  ["contact_title", "Title"],
  ["email", "Email"],
  ["website", "Website"],
  ["industry", "Industry"],
  ["address_line", "Address"],
  ["city", "City"],
  ["region", "State / province"],
  ["postal_code", "Postal code"],
  ["country_code", "Country"],
  ["timezone", "Timezone"],
] as const;

type EditKey = (typeof EDITABLE)[number][0];

export function LeadDrawer({ leadId, onClose }: { leadId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const editable = can("admin", "manager");
  const lead = useQuery({
    queryKey: ["lead", leadId],
    queryFn: () => api.get<Lead>(`/api/v1/leads/${leadId}`),
  });
  const timeline = useQuery({
    queryKey: ["lead-timeline", leadId],
    queryFn: () => api.get<TimelineItem[]>(`/api/v1/leads/${leadId}/timeline`),
  });
  const [form, setForm] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);

  const startEditing = (l: Lead) => {
    const f: Record<string, string> = { notes: l.notes ?? "" };
    for (const [k] of EDITABLE) f[k] = (l[k as EditKey] as string | null) ?? "";
    setForm(f);
    setEditing(true);
  };

  const save = useMutation({
    mutationFn: () => {
      const l = lead.data as Lead;
      const changes: Record<string, string | null> = {};
      for (const [k, v] of Object.entries(form)) {
        const current = (l[k as keyof Lead] as string | null) ?? "";
        if (v !== current) changes[k] = v === "" ? null : v;
      }
      return api.patch<Lead>(`/api/v1/leads/${leadId}`, changes);
    },
    onSuccess: (l) => {
      qc.setQueryData(["lead", leadId], l);
      qc.invalidateQueries({ queryKey: ["leads", l.campaign_id] });
      qc.invalidateQueries({ queryKey: ["lead-timeline", leadId] });
      setEditing(false);
    },
  });

  const l = lead.data;
  return (
    <Drawer
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          {l?.business_name || l?.contact_name || l?.phone_e164 || "Lead"}
          {l && <Badge value={l.status} />}
        </div>
      }
    >
      <ErrorText error={lead.error} />
      {l && (
        <div className="space-y-6">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-slate-500">Phone</dt>
            <dd className="font-mono">{l.phone_e164}</dd>
            {l.phone_alt_e164 && (
              <>
                <dt className="text-slate-500">Alt. phone</dt>
                <dd className="font-mono">{l.phone_alt_e164}</dd>
              </>
            )}
            <dt className="text-slate-500">Local time</dt>
            <dd>
              {localTime(l.timezone)} <span className="text-slate-400">({l.timezone ?? "unknown"})</span>
            </dd>
            <dt className="text-slate-500">Attempts</dt>
            <dd>{l.attempts}</dd>
            <dt className="text-slate-500">Last disposition</dt>
            <dd>{l.last_disposition ?? "—"}</dd>
            <dt className="text-slate-500">Next attempt</dt>
            <dd>{dateTime(l.next_attempt_at)}</dd>
            <dt className="text-slate-500">Source</dt>
            <dd>{l.source}</dd>
          </dl>

          {editing ? (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <div className="grid grid-cols-2 gap-3">
                {EDITABLE.map(([k, labelText]) => (
                  <Field key={k} label={labelText}>
                    <Input value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                  </Field>
                ))}
              </div>
              <Field label="Notes">
                <Textarea rows={3} value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </Field>
              <ErrorText error={save.error} />
              <div className="flex gap-2">
                <Button type="submit" disabled={save.isPending}>Save</Button>
                <Button variant="secondary" onClick={() => setEditing(false)}>Cancel</Button>
              </div>
            </form>
          ) : (
            <div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                {EDITABLE.map(([k, labelText]) => (
                  <div key={k} className="contents">
                    <dt className="text-slate-500">{labelText}</dt>
                    <dd className="break-words">{(l[k as EditKey] as string | null) || "—"}</dd>
                  </div>
                ))}
                <dt className="text-slate-500">Notes</dt>
                <dd className="whitespace-pre-wrap">{l.notes || "—"}</dd>
              </dl>
              {editable && (
                <Button variant="secondary" className="mt-3" onClick={() => startEditing(l)}>
                  Edit
                </Button>
              )}
            </div>
          )}

          {Object.keys(l.custom).length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-medium">Custom fields</h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                {Object.entries(l.custom).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-slate-500">{k}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          <div>
            <h3 className="mb-2 text-sm font-medium">Timeline</h3>
            <ol className="space-y-2 border-l border-slate-200 pl-4 text-sm">
              {timeline.data?.map((t, i) => (
                <li key={i}>
                  <div className="font-medium">{t.title}</div>
                  <div className="text-xs text-slate-500">{dateTime(t.ts)}</div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </Drawer>
  );
}
