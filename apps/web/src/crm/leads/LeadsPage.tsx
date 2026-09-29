import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type RowSelectionState,
} from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, ErrorText, Input, PageHeader, Select, Table, td, th } from "../../components/ui";
import { api, qs } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { label, localTime } from "../../lib/format";
import { useCampaigns } from "../../lib/queries";
import { LEAD_STATUSES, type BulkResult, type Lead, type Page } from "../../lib/types";
import { ImportWizard } from "./ImportWizard";
import { LeadDrawer } from "./LeadDrawer";

const col = createColumnHelper<Lead>();
const PAGE_SIZE = 50;

export function LeadsPage() {
  const { can } = useAuth();
  const manager = can("admin", "manager");
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const campaigns = useCampaigns();
  const campaignId = params.get("campaign") ?? campaigns.data?.[0]?.id ?? "";
  const campaign = campaigns.data?.find((c) => c.id === campaignId);
  const status = params.get("status") ?? "";
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? "1");
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [openLead, setOpenLead] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [moveTarget, setMoveTarget] = useState("");
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);

  const setParam = (updates: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(updates)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace: true });
  };

  useEffect(() => {
    const t = setTimeout(() => {
      if (search !== q) setParam({ q: search, page: "" });
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  useEffect(() => setSelection({}), [campaignId, status, q, page]);

  const leads = useQuery({
    queryKey: ["leads", campaignId, status, q, page],
    queryFn: () =>
      api.get<Page<Lead>>(
        `/api/v1/campaigns/${campaignId}/leads${qs({ status: status || undefined, q, page, page_size: PAGE_SIZE })}`,
      ),
    enabled: !!campaignId,
    placeholderData: keepPreviousData,
  });

  const columns = useMemo(
    () => [
      col.display({
        id: "select",
        header: ({ table }) => (
          <input
            type="checkbox"
            aria-label="Select all"
            checked={table.getIsAllRowsSelected()}
            onChange={table.getToggleAllRowsSelectedHandler()}
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            aria-label="Select row"
            checked={row.getIsSelected()}
            onClick={(e) => e.stopPropagation()}
            onChange={row.getToggleSelectedHandler()}
          />
        ),
      }),
      col.accessor((l) => l.business_name ?? l.contact_name ?? "—", {
        id: "name",
        header: "Business / contact",
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.business_name ?? "—"}</div>
            <div className="text-xs text-slate-500">{row.original.contact_name}</div>
          </div>
        ),
      }),
      col.accessor("phone_e164", {
        header: "Phone",
        cell: (c) => <span className="font-mono text-xs">{c.getValue()}</span>,
      }),
      col.accessor("status", { header: "Status", cell: (c) => <Badge value={c.getValue()} /> }),
      col.accessor((l) => [l.city, l.region, l.country_code].filter(Boolean).join(", "), {
        id: "location",
        header: "Location",
      }),
      col.accessor("timezone", {
        header: "Timezone",
        cell: (c) => (
          <div>
            <div>{c.getValue() ?? "—"}</div>
            <div className="text-xs text-slate-500">{localTime(c.getValue())}</div>
          </div>
        ),
      }),
      col.accessor("attempts", { header: "Attempts" }),
      col.accessor("last_disposition", {
        header: "Last disposition",
        cell: (c) => (c.getValue() ? label(c.getValue() as string) : "—"),
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: leads.data?.items ?? [],
    columns,
    state: { rowSelection: selection },
    getRowId: (l) => l.id,
    onRowSelectionChange: setSelection,
    getCoreRowModel: getCoreRowModel(),
    enableRowSelection: manager,
  });

  const selectedIds = Object.keys(selection).filter((k) => selection[k]);
  const bulk = useMutation({
    mutationFn: async (action: "requeue" | "move" | "dnc" | "export") => {
      const body = {
        ids: selectedIds,
        action,
        target_campaign_id: action === "move" ? moveTarget : undefined,
      };
      if (action === "export") {
        await api.download("/api/v1/leads/bulk", body, "leads.csv");
        return null;
      }
      return api.post<BulkResult>("/api/v1/leads/bulk", body);
    },
    onSuccess: (res) => {
      if (res) {
        setBulkMsg(
          `${label(res.action)}: ${res.updated} updated` +
            (res.skipped.length ? `, ${res.skipped.length} skipped (${res.skipped[0].reason}${res.skipped.length > 1 ? ", …" : ""})` : ""),
        );
        setSelection({});
        qc.invalidateQueries({ queryKey: ["leads"] });
        qc.invalidateQueries({ queryKey: ["campaigns"] });
      }
    },
  });

  const total = leads.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <PageHeader
        title="Leads"
        actions={
          manager && campaign && campaign.status !== "completed" && (
            <Button onClick={() => setImporting(true)}>Import CSV</Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select
          aria-label="Campaign"
          className="w-64"
          value={campaignId}
          onChange={(e) => setParam({ campaign: e.target.value, page: "" })}
        >
          {campaigns.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Status"
          className="w-44"
          value={status}
          onChange={(e) => setParam({ status: e.target.value, page: "" })}
        >
          <option value="">All statuses</option>
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {label(s)}
              {campaign?.lead_counts[s] ? ` (${campaign.lead_counts[s]})` : ""}
            </option>
          ))}
        </Select>
        <Input
          aria-label="Search"
          className="w-64"
          placeholder="Search name, phone, email, city…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-sm text-slate-500">{leads.data ? `${total} leads` : "…"}</span>
      </div>

      {campaigns.data?.length === 0 && (
        <p className="text-slate-500">Create a campaign first, then import leads into it.</p>
      )}

      {manager && selectedIds.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-indigo-50 px-3 py-2 text-sm">
          <span className="font-medium">{selectedIds.length} selected</span>
          <Button variant="secondary" onClick={() => bulk.mutate("requeue")}>Requeue</Button>
          <Select aria-label="Move to campaign" className="w-52" value={moveTarget} onChange={(e) => setMoveTarget(e.target.value)}>
            <option value="">Move to campaign…</option>
            {campaigns.data?.filter((c) => c.id !== campaignId && c.status !== "completed").map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
          <Button variant="secondary" disabled={!moveTarget} onClick={() => bulk.mutate("move")}>Move</Button>
          <Button
            variant="danger"
            onClick={() => {
              if (confirm(`Add ${selectedIds.length} phone number(s) to the global DNC list?`)) bulk.mutate("dnc");
            }}
          >
            Mark DNC
          </Button>
          <Button variant="secondary" onClick={() => bulk.mutate("export")}>Export CSV</Button>
        </div>
      )}
      {bulkMsg && <div className="mb-3 text-sm text-slate-600">{bulkMsg}</div>}
      <ErrorText error={leads.error ?? bulk.error} />

      <Table>
        <thead className="bg-slate-50">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => (
                <th key={h.id} className={th}>
                  {flexRender(h.column.columnDef.header, h.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-slate-100">
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpenLead(row.original.id)}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className={td}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
          {leads.data && leads.data.items.length === 0 && (
            <tr>
              <td className={`${td} text-slate-500`} colSpan={columns.length}>
                No leads match.
              </td>
            </tr>
          )}
        </tbody>
      </Table>

      <div className="mt-3 flex items-center justify-end gap-2 text-sm">
        <Button variant="secondary" disabled={page <= 1} onClick={() => setParam({ page: String(page - 1) })}>
          Previous
        </Button>
        <span>
          Page {page} of {pages}
        </span>
        <Button variant="secondary" disabled={page >= pages} onClick={() => setParam({ page: String(page + 1) })}>
          Next
        </Button>
      </div>

      {importing && campaign && <ImportWizard campaign={campaign} onClose={() => setImporting(false)} />}
      {openLead && <LeadDrawer leadId={openLead} onClose={() => setOpenLead(null)} />}
    </div>
  );
}
