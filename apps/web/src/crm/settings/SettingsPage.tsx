import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import {
  Badge,
  Button,
  Checkbox,
  ErrorText,
  Field,
  Input,
  PageHeader,
  Select,
  Table,
  Tabs,
  td,
  th,
} from "../../components/ui";
import { api, qs } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { dateTime, TIMEZONES } from "../../lib/format";
import { useClients, useTeams, useTrunks, useUsers } from "../../lib/queries";
import type { DncEntry, Market, Page, Role, SipTrunk, Team, User } from "../../lib/types";

type TabKey = "users" | "teams" | "dnc" | "trunks";

export function SettingsPage() {
  const { can } = useAuth();
  const mgr = can("admin", "manager");
  const tabs = [
    ...(mgr ? [{ key: "users" as const, label: "Users" }] : []),
    { key: "teams" as const, label: "Teams" },
    { key: "dnc" as const, label: "DNC list" },
    ...(mgr ? [{ key: "trunks" as const, label: "SIP trunks" }] : []),
  ];
  const [tab, setTab] = useState<TabKey>(tabs[0].key);
  return (
    <div>
      <PageHeader title="Settings" />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "users" && <UsersTab />}
      {tab === "teams" && <TeamsTab />}
      {tab === "dnc" && <DncTab />}
      {tab === "trunks" && <TrunksTab />}
    </div>
  );
}

// --- users -----------------------------------------------------------------------------------

function UsersTab() {
  const qc = useQueryClient();
  const { can, user: me } = useAuth();
  const admin = can("admin");
  const users = useUsers();
  const clients = useClients();
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "rep" as Role, client_id: "" });

  const create = useMutation({
    mutationFn: () => api.post<User>("/api/v1/users", { ...form, client_id: form.client_id || null }),
    onSuccess: () => {
      setForm({ email: "", full_name: "", password: "", role: "rep", client_id: "" });
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: Role; is_active?: boolean; password?: string }) =>
      api.patch<User>(`/api/v1/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <div className="space-y-6">
      <ErrorText error={users.error ?? update.error} />
      <Table>
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Email</th>
            <th className={th}>Name</th>
            <th className={th}>Role</th>
            <th className={th}>Client</th>
            <th className={th}>Active</th>
            {admin && <th className={th}></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {users.data?.map((u) => (
            <tr key={u.id}>
              <td className={td}>{u.email}</td>
              <td className={td}>{u.full_name ?? "—"}</td>
              <td className={td}>
                {admin ? (
                  <Select aria-label={`Role for ${u.email}`} className="w-28" value={u.role}
                    onChange={(e) => update.mutate({ id: u.id, role: e.target.value as Role })}>
                    {(["admin", "manager", "rep", "qa"] as Role[]).map((r) => <option key={r}>{r}</option>)}
                  </Select>
                ) : (
                  u.role
                )}
              </td>
              <td className={td}>{clients.data?.find((c) => c.id === u.client_id)?.name ?? "—"}</td>
              <td className={td}>
                <Checkbox label="" checked={u.is_active} disabled={!admin || u.id === me?.id}
                  onChange={(v) => update.mutate({ id: u.id, is_active: v })} />
              </td>
              {admin && (
                <td className={`${td} text-right`}>
                  <Button variant="ghost" onClick={() => {
                    const pw = prompt(`New password for ${u.email} (min 8 characters)`);
                    if (pw) update.mutate({ id: u.id, password: pw });
                  }}>
                    Reset password
                  </Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </Table>

      {admin && (
        <form className="max-w-3xl space-y-3 rounded-lg border border-slate-200 bg-white p-4"
          onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <h3 className="font-medium">Add user</h3>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <Field label="Email"><Input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Full name"><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
            <Field label="Password" hint="8–72 characters"><Input type="password" required minLength={8} maxLength={72} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
            <Field label="Role">
              <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                {(["admin", "manager", "rep", "qa"] as Role[]).map((r) => <option key={r}>{r}</option>)}
              </Select>
            </Field>
            <Field label="Client (optional)">
              <Select value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
                <option value="">—</option>
                {clients.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
          </div>
          <ErrorText error={create.error} />
          <Button type="submit" disabled={create.isPending}>Add user</Button>
        </form>
      )}
    </div>
  );
}

// --- teams -----------------------------------------------------------------------------------

function TeamsTab() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const mgr = can("admin", "manager");
  const teams = useTeams();
  const users = useUsers(mgr);
  const [editing, setEditing] = useState<Team | "new" | null>(null);

  return (
    <div className="space-y-6">
      <ErrorText error={teams.error} />
      <Table>
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Timezone</th>
            <th className={th}>Notify emails</th>
            <th className={th}>Members</th>
            {mgr && <th className={th}></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {teams.data?.map((t) => (
            <tr key={t.id}>
              <td className={td}>{t.name}</td>
              <td className={td}>{t.timezone}</td>
              <td className={td}>{t.notify_emails.join(", ") || "—"}</td>
              <td className={td}>
                {t.member_ids.map((id) => users.data?.find((u) => u.id === id)?.email ?? "…").join(", ") || "—"}
              </td>
              {mgr && (
                <td className={`${td} text-right`}>
                  <Button variant="ghost" onClick={() => setEditing(t)}>Edit</Button>
                </td>
              )}
            </tr>
          ))}
          {teams.data?.length === 0 && (
            <tr><td className={`${td} text-slate-500`} colSpan={5}>No teams yet.</td></tr>
          )}
        </tbody>
      </Table>
      {mgr && !editing && <Button onClick={() => setEditing("new")}>New team</Button>}
      {mgr && editing && (
        <TeamForm
          team={editing === "new" ? null : editing}
          users={users.data ?? []}
          onDone={() => {
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["teams"] });
          }}
        />
      )}
    </div>
  );
}

function TeamForm({ team, users, onDone }: { team: Team | null; users: User[]; onDone: () => void }) {
  const [name, setName] = useState(team?.name ?? "");
  const [tz, setTz] = useState(team?.timezone ?? "America/New_York");
  const [emails, setEmails] = useState(team?.notify_emails.join(", ") ?? "");
  const [webhook, setWebhook] = useState(team?.webhook_url ?? "");
  const [members, setMembers] = useState<string[]>(team?.member_ids ?? []);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        timezone: tz,
        notify_emails: emails.split(",").map((s) => s.trim()).filter(Boolean),
        webhook_url: webhook || null,
        member_ids: members,
      };
      return team ? api.patch(`/api/v1/teams/${team.id}`, body) : api.post("/api/v1/teams", body);
    },
    onSuccess: onDone,
  });
  return (
    <form className="max-w-3xl space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <h3 className="font-medium">{team ? `Edit ${team.name}` : "New team"}</h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label="Name"><Input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Timezone">
          <Select value={tz} onChange={(e) => setTz(e.target.value)}>
            {TIMEZONES.map((z) => <option key={z}>{z}</option>)}
          </Select>
        </Field>
        <Field label="Notify emails" hint="Comma-separated"><Input value={emails} onChange={(e) => setEmails(e.target.value)} /></Field>
        <Field label="Webhook URL (optional)"><Input value={webhook} onChange={(e) => setWebhook(e.target.value)} /></Field>
      </div>
      <div>
        <div className="mb-1 text-xs font-medium text-slate-600">Members</div>
        <div className="grid grid-cols-2 gap-1 md:grid-cols-3">
          {users.map((u) => (
            <Checkbox key={u.id} label={u.email} checked={members.includes(u.id)}
              onChange={(v) => setMembers(v ? [...members, u.id] : members.filter((m) => m !== u.id))} />
          ))}
        </div>
      </div>
      <ErrorText error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>Save</Button>
        <Button variant="secondary" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

// --- dnc -------------------------------------------------------------------------------------

function DncTab() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const clients = useClients();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [form, setForm] = useState({ phone: "", scope: "global", client_id: "", reason: "", default_region: "US" });
  const list = useQuery({
    queryKey: ["dnc", q, page],
    queryFn: () => api.get<Page<DncEntry>>(`/api/v1/dnc${qs({ q, page, page_size: 50 })}`),
  });
  const add = useMutation({
    mutationFn: () =>
      api.post<DncEntry>("/api/v1/dnc", {
        ...form,
        client_id: form.scope === "client" ? form.client_id : null,
        reason: form.reason || null,
      }),
    onSuccess: () => {
      setForm({ ...form, phone: "", reason: "" });
      qc.invalidateQueries({ queryKey: ["dnc"] });
      qc.invalidateQueries({ queryKey: ["leads"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/dnc/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dnc"] }),
  });
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / 50));

  return (
    <div className="space-y-6">
      <form className="flex max-w-4xl flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4"
        onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
        <Field label="Phone"><Input required value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
        <Field label="Country (if no +code)">
          <Select value={form.default_region} onChange={(e) => setForm({ ...form, default_region: e.target.value })}>
            {["US", "CA", "PH"].map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label="Scope">
          <Select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
            <option value="global">Global</option>
            <option value="client">Client</option>
          </Select>
        </Field>
        {form.scope === "client" && (
          <Field label="Client">
            <Select required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
              <option value="">Select…</option>
              {clients.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
          </Field>
        )}
        <Field label="Reason"><Input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        <Button type="submit" disabled={add.isPending}>Add to DNC</Button>
        <div className="w-full"><ErrorText error={add.error} /></div>
      </form>

      <Input aria-label="Search DNC" className="w-64" placeholder="Search phone…" value={q}
        onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      <ErrorText error={list.error ?? remove.error} />
      <Table>
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Phone</th>
            <th className={th}>Scope</th>
            <th className={th}>Reason</th>
            <th className={th}>Source</th>
            <th className={th}>Added</th>
            {can("admin") && <th className={th}></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {list.data?.items.map((d) => (
            <tr key={d.id}>
              <td className={`${td} font-mono text-xs`}>{d.phone_e164}</td>
              <td className={td}>
                <Badge value={d.scope} />{" "}
                {d.client_id && clients.data?.find((c) => c.id === d.client_id)?.name}
              </td>
              <td className={td}>{d.reason ?? "—"}</td>
              <td className={td}>{d.source ?? "—"}</td>
              <td className={td}>{dateTime(d.created_at)}</td>
              {can("admin") && (
                <td className={`${td} text-right`}>
                  <Button variant="ghost" onClick={() => {
                    if (confirm(`Remove ${d.phone_e164} from the DNC list? This is audit-logged.`)) remove.mutate(d.id);
                  }}>
                    Remove
                  </Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="flex items-center justify-end gap-2 text-sm">
        <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
        <span>Page {page} of {pages}</span>
        <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

// --- sip trunks --------------------------------------------------------------------------------

function TrunksTab() {
  const qc = useQueryClient();
  const { can } = useAuth();
  const admin = can("admin");
  const trunks = useTrunks();
  const [editing, setEditing] = useState<SipTrunk | "new" | null>(null);
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-500">
        Trunks and caller IDs are data, not env vars: create the trunk in LiveKit (<code>lk sip outbound create</code>)
        and paste its ID here.
      </p>
      <ErrorText error={trunks.error} />
      <Table>
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Market</th>
            <th className={th}>Provider</th>
            <th className={th}>LiveKit trunk ID</th>
            <th className={th}>Caller IDs</th>
            <th className={th}>Active</th>
            {admin && <th className={th}></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {trunks.data?.map((t) => (
            <tr key={t.id}>
              <td className={td}>{t.name}</td>
              <td className={td}>{t.market}</td>
              <td className={td}>{t.provider ?? "—"}</td>
              <td className={`${td} font-mono text-xs`}>{t.livekit_trunk_id ?? "—"}</td>
              <td className={`${td} font-mono text-xs`}>{t.caller_ids.join(", ") || "—"}</td>
              <td className={td}>{t.is_active ? "yes" : "no"}</td>
              {admin && (
                <td className={`${td} text-right`}>
                  <Button variant="ghost" onClick={() => setEditing(t)}>Edit</Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </Table>
      {admin && !editing && <Button onClick={() => setEditing("new")}>New trunk</Button>}
      {admin && editing && (
        <TrunkForm trunk={editing === "new" ? null : editing} onDone={() => {
          setEditing(null);
          qc.invalidateQueries({ queryKey: ["sip-trunks"] });
        }} />
      )}
    </div>
  );
}

function TrunkForm({ trunk, onDone }: { trunk: SipTrunk | null; onDone: () => void }) {
  const [f, setF] = useState({
    name: trunk?.name ?? "",
    market: trunk?.market ?? ("US" as Market),
    provider: trunk?.provider ?? "",
    livekit_trunk_id: trunk?.livekit_trunk_id ?? "",
    caller_ids: trunk?.caller_ids.join("\n") ?? "",
    is_active: trunk?.is_active ?? true,
  });
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...f,
        provider: f.provider || null,
        livekit_trunk_id: f.livekit_trunk_id || null,
        caller_ids: f.caller_ids.split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
      };
      return trunk ? api.patch(`/api/v1/sip-trunks/${trunk.id}`, body) : api.post("/api/v1/sip-trunks", body);
    },
    onSuccess: onDone,
  });
  return (
    <form className="max-w-3xl space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <h3 className="font-medium">{trunk ? `Edit ${trunk.name}` : "New SIP trunk"}</h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label="Name"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Market">
          <Select value={f.market} onChange={(e) => setF({ ...f, market: e.target.value as Market })}>
            {(["US", "CA", "PH", "OTHER"] as Market[]).map((m) => <option key={m}>{m}</option>)}
          </Select>
        </Field>
        <Field label="Provider"><Input value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })} /></Field>
        <Field label="LiveKit trunk ID"><Input value={f.livekit_trunk_id} onChange={(e) => setF({ ...f, livekit_trunk_id: e.target.value })} /></Field>
        <Field label="Caller IDs" hint="One per line; must be numbers you own" className="md:col-span-2">
          <textarea rows={3} className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm"
            value={f.caller_ids} onChange={(e) => setF({ ...f, caller_ids: e.target.value })} />
        </Field>
        <Checkbox label="Active" checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} />
      </div>
      <ErrorText error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>Save</Button>
        <Button variant="secondary" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}
