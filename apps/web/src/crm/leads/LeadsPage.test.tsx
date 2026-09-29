import { fireEvent, screen, within } from "@testing-library/react";
import { mockApi, renderApp } from "../../testing";

const ADMIN = { id: "u1", email: "a@b.c", full_name: null, role: "admin", client_id: null,
  is_active: true, created_at: "2026-09-29T00:00:00Z" };
const CAMPAIGN = {
  id: "c1", client_id: "cl1", name: "YP SEO US (test)", status: "draft", market: "US",
  country_codes: ["US", "CA"], default_timezone: "America/New_York", languages: ["en"],
  sip_trunk_id: null, caller_id: null, calling_window: {}, max_attempts: 3,
  retry_spacing_hours: 4, voicemail_counts_as_attempt: false, concurrency: 2, daily_cap: null,
  daily_budget_usd: null, test_mode: true, test_allowlist: [], requeue_no_show: false,
  appointment_settings: {}, compliance: {}, active_playbook_version_id: null,
  created_at: "", updated_at: "", lead_counts: { new: 1 },
};
const LEAD = {
  id: "l1", campaign_id: "c1", external_id: null, source: "csv", business_name: "Makati Cleaning",
  contact_name: "Ann", contact_title: null, phone_e164: "+639175550101", phone_alt_e164: null,
  email: null, address_line: null, city: "Makati", region: "Metro Manila", country_code: "PH",
  timezone: "Asia/Manila", website: null, industry: null, custom: { "Google Rating": "4.5" },
  status: "new", attempts: 0, next_attempt_at: null, last_attempt_at: null,
  last_disposition: null, priority: 0, notes: null, created_at: "2026-09-29T00:00:00Z",
};
const REPORT = {
  import_id: null, dry_run: true, filename: "x.csv", headers: ["Business Name", "Phone"],
  column_map: { phone: "Phone", business_name: "Business Name" },
  suggested_column_map: { phone: "Phone", business_name: "Business Name" },
  row_count: 50, imported: 45, skipped_dupe: 3, skipped_dnc: 2, skipped_invalid: 0,
  issues: [{ row: 7, reason: "dnc", detail: "phone is on the DNC list", value: "+13125550149" }],
  preview: [{ row: 1, status: "ok", phone_e164: "+639175550101", business_name: "Makati Cleaning",
    contact_name: "Ann", city: "Makati", region: "Metro Manila", country_code: "PH",
    timezone: "Asia/Manila" }],
};

beforeEach(() => {
  localStorage.setItem("maria.token", "tok");
});

test("leads table shows timezone and the import wizard walks to the report", async () => {
  const bodies: FormData[] = [];
  mockApi({
    "GET /api/v1/me": () => ADMIN,
    "GET /health": () => ({ ok: true }),
    "GET /api/v1/campaigns": () => [CAMPAIGN],
    "GET /api/v1/campaigns/c1/leads": () => ({ items: [LEAD], total: 1, page: 1, page_size: 50 }),
    "POST /api/v1/campaigns/c1/leads/import": (_u, init) => {
      const fd = init?.body as FormData;
      bodies.push(fd);
      const dry = fd.get("dry_run") === "true";
      return { ...REPORT, dry_run: dry, import_id: dry ? null : "imp1" };
    },
  });
  renderApp("/crm/leads");

  const row = (await screen.findByText("Makati Cleaning")).closest("tr") as HTMLElement;
  expect(within(row).getByText("Asia/Manila")).toBeInTheDocument();
  expect(within(row).getByText("+639175550101")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Import CSV" }));
  const dialog = within(screen.getByRole("dialog"));
  const file = new File(["Business Name,Phone\n"], "x.csv", { type: "text/csv" });
  fireEvent.change(dialog.getByLabelText("CSV file"), { target: { files: [file] } });
  fireEvent.click(dialog.getByRole("button", { name: "Next" }));

  expect(await dialog.findByLabelText("Phone")).toHaveValue("Phone");
  fireEvent.click(dialog.getByRole("button", { name: "Preview" }));
  expect(await screen.findByText("Will import")).toBeInTheDocument();
  expect(JSON.parse(String(bodies[1].get("column_map")))).toEqual(REPORT.column_map);

  fireEvent.click(dialog.getByRole("button", { name: "Import 45 leads" }));
  expect(await screen.findByText("Import complete.")).toBeInTheDocument();
  expect(screen.getByTestId("count-Imported")).toHaveTextContent("45");
  expect(screen.getByTestId("count-Duplicates")).toHaveTextContent("3");
  expect(screen.getByTestId("count-On DNC")).toHaveTextContent("2");
  expect(bodies[2].get("dry_run")).toBe("false");
});
