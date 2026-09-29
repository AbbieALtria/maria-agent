import { Link } from "react-router-dom";
import { Badge, Button, ErrorText, PageHeader, Table, td, th } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { useCampaigns, useClients } from "../../lib/queries";

export function CampaignsPage() {
  const { can } = useAuth();
  const campaigns = useCampaigns();
  const clients = useClients();
  const clientName = (id: string) => clients.data?.find((c) => c.id === id)?.name ?? "—";

  return (
    <div>
      <PageHeader
        title="Campaigns"
        actions={
          can("admin", "manager") && (
            <Link to="/crm/campaigns/new">
              <Button>New campaign</Button>
            </Link>
          )
        }
      />
      <ErrorText error={campaigns.error} />
      <Table>
        <thead className="bg-slate-50">
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Client</th>
            <th className={th}>Status</th>
            <th className={th}>Market</th>
            <th className={th}>Leads</th>
            <th className={th}>Playbook</th>
            <th className={th}></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {campaigns.data?.map((c) => {
            const total = Object.values(c.lead_counts).reduce((a, b) => a + b, 0);
            return (
              <tr key={c.id} className="hover:bg-slate-50">
                <td className={td}>
                  <Link to={`/crm/campaigns/${c.id}`} className="font-medium text-indigo-700">
                    {c.name}
                  </Link>
                </td>
                <td className={td}>{clientName(c.client_id)}</td>
                <td className={td}>
                  <div className="flex gap-1">
                    <Badge value={c.status} />
                    {c.test_mode && <Badge value="test mode" />}
                  </div>
                </td>
                <td className={td}>
                  {c.market}
                  {c.country_codes.length > 0 && (
                    <span className="text-slate-400"> ({c.country_codes.join(", ")})</span>
                  )}
                </td>
                <td className={td}>{total}</td>
                <td className={td}>{c.active_playbook_version_id ? "active" : "—"}</td>
                <td className={`${td} text-right`}>
                  <Link to={`/crm/leads?campaign=${c.id}`} className="text-sm text-indigo-700">
                    Leads →
                  </Link>
                </td>
              </tr>
            );
          })}
          {campaigns.data?.length === 0 && (
            <tr>
              <td className={`${td} text-slate-500`} colSpan={7}>
                No campaigns yet.
              </td>
            </tr>
          )}
        </tbody>
      </Table>
    </div>
  );
}
