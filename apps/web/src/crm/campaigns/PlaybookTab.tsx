import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, ErrorText, Field, Input, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { dateTime } from "../../lib/format";
import type { Campaign, PlaybookVersion } from "../../lib/types";

/** Plain JSON textarea for now; the schema-aware editor + simulator comes with Phase 2/3. */
export function PlaybookTab({ campaign, editable }: { campaign: Campaign; editable: boolean }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const key = ["playbooks", campaign.id];
  const versions = useQuery({
    queryKey: key,
    queryFn: () => api.get<PlaybookVersion[]>(`/api/v1/campaigns/${campaign.id}/playbooks`),
  });
  const active = versions.data?.find((v) => v.is_active) ?? versions.data?.[0];
  const [text, setText] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const value = text ?? (active ? JSON.stringify(active.playbook, null, 2) : "{\n  \"schema_version\": \"1.0\"\n}");

  const save = useMutation({
    mutationFn: (playbook: unknown) =>
      api.post<PlaybookVersion>(`/api/v1/campaigns/${campaign.id}/playbooks`, {
        playbook,
        notes: notes || null,
      }),
    onSuccess: () => {
      setText(null);
      setNotes("");
      qc.invalidateQueries({ queryKey: key });
    },
  });

  const activate = useMutation({
    mutationFn: ({ id, override }: { id: string; override?: string }) =>
      api.post(`/api/v1/campaigns/${campaign.id}/playbooks/${id}/activate`, {
        override_reason: override ?? null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["campaign", campaign.id] });
    },
  });

  function submit() {
    try {
      const parsed = JSON.parse(value);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
        throw new Error("Playbook must be a JSON object");
      setParseError(null);
      save.mutate(parsed);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
      <div className="space-y-3">
        <Field label="Playbook JSON" hint="Saving creates a new, inactive version. Activation is a separate, audit-logged step.">
          <Textarea
            rows={22}
            spellCheck={false}
            className="font-mono text-xs"
            value={value}
            onChange={(e) => setText(e.target.value)}
            disabled={!editable}
          />
        </Field>
        {editable && (
          <>
            <Field label="Version notes">
              <Input value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
            <ErrorText error={parseError ?? save.error} />
            <Button onClick={submit} disabled={save.isPending}>
              Save as new version
            </Button>
          </>
        )}
      </div>
      <div>
        <h3 className="mb-2 text-sm font-medium">Versions</h3>
        <ErrorText error={activate.error} />
        <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 bg-white">
          {versions.data?.map((v) => (
            <li key={v.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
              <button type="button" className="text-left" onClick={() => setText(JSON.stringify(v.playbook, null, 2))}>
                <div className="font-medium">v{v.version}</div>
                <div className="text-xs text-slate-500">{dateTime(v.created_at)}</div>
                {v.notes && <div className="text-xs text-slate-500">{v.notes}</div>}
              </button>
              {v.is_active ? (
                <Badge value="active" />
              ) : (
                editable && (
                  <Button
                    variant="secondary"
                    onClick={() => {
                      if (!confirm(`Activate v${v.version}? Maria will use it for new calls.`)) return;
                      activate.mutate(
                        { id: v.id },
                        {
                          onError: (err) => {
                            if (can("admin") && String(err).includes("eval gate")) {
                              const reason = prompt("Eval gate not met. Admin override reason:");
                              if (reason) activate.mutate({ id: v.id, override: reason });
                            }
                          },
                        },
                      );
                    }}
                  >
                    Activate
                  </Button>
                )
              )}
            </li>
          ))}
          {versions.data?.length === 0 && (
            <li className="px-3 py-2 text-sm text-slate-500">No versions yet.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
