import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { routes } from "./routes";

test("renders the CRM shell at /crm", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true }))));
  const router = createMemoryRouter(routes, { initialEntries: ["/crm"] });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  expect(screen.getByText("Maria CRM")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  expect(await screen.findByText("API online")).toBeInTheDocument();
});
