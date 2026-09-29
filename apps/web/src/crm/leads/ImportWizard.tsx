import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, ErrorText, Modal, Select, Table, td, th } from "../../components/ui";
import { api } from "../../lib/api";
import type { Campaign, ImportReport } from "../../lib/types";

const FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: "phone", label: "Phone", required: true },
  { key: "phone_alt", label: "Alt. phone" },
  { key: "business_name", label: "Business name" },
  { key: "contact_name", label: "Contact name" },
  { key: "contact_title", label: "Contact title" },
  { key: "email", label: "Email" },
  { key: "address_line", label: "Address" },
  { key: "city", label: "City" },
  { key: "region", label: "State / province" },
  { key: "postal_code", label: "Postal code" },
  { key: "country_code", label: "Country" },
  { key: "timezone", label: "Timezone" },
  { key: "website", label: "Website" },
  { key: "industry", label: "Industry" },
  { key: "external_id", label: "External ID" },
  { key: "notes", label: "Notes" },
];

type Step = "upload" | "map" | "preview" | "done";

function Counts({ r, final }: { r: ImportReport; final: boolean }) {
  const items = [
    [final ? "Imported" : "Will import", r.imported, "text-emerald-700"],
    ["Duplicates", r.skipped_dupe, "text-slate-700"],
    ["On DNC", r.skipped_dnc, "text-red-700"],
    ["Invalid phone", r.skipped_invalid, "text-amber-700"],
  ] as const;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <div className="rounded-md border border-slate-200 p-3">
        <div className="text-xs text-slate-500">Rows</div>
        <div className="text-xl font-semibold">{r.row_count}</div>
      </div>
      {items.map(([label, n, cls]) => (
        <div key={label} className="rounded-md border border-slate-200 p-3">
          <div className="text-xs text-slate-500">{label}</div>
          <div className={`text-xl font-semibold ${cls}`} data-testid={`count-${label}`}>
            {n}
          </div>
        </div>
      ))}
    </div>
  );
}

function Issues({ r }: { r: ImportReport }) {
  if (!r.issues.length) return null;
  return (
    <details className="text-sm" open={r.issues.length <= 10}>
      <summary className="cursor-pointer text-slate-600">
        {r.issues.length} skipped row{r.issues.length > 1 ? "s" : ""}
      </summary>
      <div className="mt-2 max-h-64 overflow-y-auto">
        <Table>
          <thead className="bg-slate-50">
            <tr>
              <th className={th}>Row</th>
              <th className={th}>Reason</th>
              <th className={th}>Detail</th>
              <th className={th}>Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {r.issues.map((i) => (
              <tr key={`${i.row}-${i.reason}`}>
                <td className={td}>{i.row}</td>
                <td className={td}><Badge value={i.reason} /></td>
                <td className={td}>{i.detail}</td>
                <td className={`${td} font-mono text-xs`}>{i.value}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </details>
  );
}

export function ImportWizard({ campaign, onClose }: { campaign: Campaign; onClose: () => void }) {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [map, setMap] = useState<Record<string, string>>({});
  const [report, setReport] = useState<ImportReport | null>(null);

  const run = useMutation({
    mutationFn: ({ dryRun, columnMap }: { dryRun: boolean; columnMap?: Record<string, string> }) => {
      const form = new FormData();
      form.append("file", file as File);
      form.append("dry_run", String(dryRun));
      if (columnMap) form.append("column_map", JSON.stringify(columnMap));
      return api.post<ImportReport>(`/api/v1/campaigns/${campaign.id}/leads/import`, form);
    },
  });

  async function analyze() {
    const r = await run.mutateAsync({ dryRun: true });
    setHeaders(r.headers);
    setMap(r.suggested_column_map);
    setStep("map");
  }

  async function preview() {
    setReport(await run.mutateAsync({ dryRun: true, columnMap: map }));
    setStep("preview");
  }

  async function confirmImport() {
    setReport(await run.mutateAsync({ dryRun: false, columnMap: map }));
    setStep("done");
    qc.invalidateQueries({ queryKey: ["leads", campaign.id] });
    qc.invalidateQueries({ queryKey: ["campaigns"] });
  }

  const unmapped = headers.filter((h) => !Object.values(map).includes(h));

  return (
    <Modal title={`Import leads into “${campaign.name}”`} onClose={onClose} wide>
      <ol className="mb-5 flex gap-4 text-xs text-slate-500">
        {(["upload", "map", "preview", "done"] as Step[]).map((s, i) => (
          <li key={s} className={s === step ? "font-semibold text-indigo-700" : ""}>
            {i + 1}. {s === "map" ? "Map columns" : s === "done" ? "Report" : s[0].toUpperCase() + s.slice(1)}
          </li>
        ))}
      </ol>

      <div className="space-y-4">
        {step === "upload" && (
          <>
            <p className="text-sm text-slate-600">
              Upload a CSV with a header row. Phone numbers are normalized to E.164 (default
              country: {campaign.country_codes[0] ?? campaign.market}), deduplicated within the
              campaign and checked against the DNC list.
            </p>
            <input
              type="file"
              accept=".csv,text/csv"
              aria-label="CSV file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <ErrorText error={run.error} />
            <div className="flex justify-end">
              <Button onClick={analyze} disabled={!file || run.isPending}>
                {run.isPending ? "Reading…" : "Next"}
              </Button>
            </div>
          </>
        )}

        {step === "map" && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {FIELDS.map((f) => (
                <label key={f.key} className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-slate-600">
                    {f.label}
                    {f.required && <span className="text-red-600"> *</span>}
                  </span>
                  <Select
                    aria-label={f.label}
                    value={map[f.key] ?? ""}
                    onChange={(e) => {
                      const next = { ...map };
                      if (e.target.value) next[f.key] = e.target.value;
                      else delete next[f.key];
                      setMap(next);
                    }}
                  >
                    <option value="">— not mapped —</option>
                    {headers.map((h) => (
                      <option key={h}>{h}</option>
                    ))}
                  </Select>
                </label>
              ))}
            </div>
            {unmapped.length > 0 && (
              <p className="text-xs text-slate-500">
                Unmapped columns are kept in the lead's custom fields: {unmapped.join(", ")}
              </p>
            )}
            <ErrorText error={run.error} />
            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setStep("upload")}>Back</Button>
              <Button onClick={preview} disabled={!map.phone || run.isPending}>
                {run.isPending ? "Checking…" : "Preview"}
              </Button>
            </div>
          </>
        )}

        {step === "preview" && report && (
          <>
            <Counts r={report} final={false} />
            <Table>
              <thead className="bg-slate-50">
                <tr>
                  {["Row", "Status", "Phone", "Business", "Contact", "City", "Region", "Country", "Timezone"].map((h) => (
                    <th key={h} className={th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {report.preview.map((p) => (
                  <tr key={p.row}>
                    <td className={td}>{p.row}</td>
                    <td className={td}><Badge value={p.status} /></td>
                    <td className={`${td} font-mono text-xs`}>{p.phone_e164}</td>
                    <td className={td}>{p.business_name}</td>
                    <td className={td}>{p.contact_name}</td>
                    <td className={td}>{p.city}</td>
                    <td className={td}>{p.region}</td>
                    <td className={td}>{p.country_code}</td>
                    <td className={td}>{p.timezone}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Issues r={report} />
            <ErrorText error={run.error} />
            <div className="flex justify-between">
              <Button variant="secondary" onClick={() => setStep("map")}>Back</Button>
              <Button onClick={confirmImport} disabled={run.isPending || report.imported === 0}>
                {run.isPending ? "Importing…" : `Import ${report.imported} leads`}
              </Button>
            </div>
          </>
        )}

        {step === "done" && report && (
          <>
            <div className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              Import complete.
            </div>
            <Counts r={report} final />
            <Issues r={report} />
            <div className="flex justify-end">
              <Button onClick={onClose}>View leads</Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
