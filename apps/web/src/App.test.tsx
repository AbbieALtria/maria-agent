import { fireEvent, screen, waitFor } from "@testing-library/react";
import { mockApi, renderApp } from "./testing";

const ADMIN = {
  id: "u1",
  email: "admin@altria.local",
  full_name: "Admin",
  role: "admin",
  client_id: null,
  is_active: true,
  created_at: "2026-09-29T00:00:00Z",
};

beforeEach(() => localStorage.clear());

test("redirects to login when signed out, then signs in to the CRM shell", async () => {
  const fetchMock = mockApi({
    "POST /api/v1/auth/login": () => ({ token: "tok", user: ADMIN }),
    "GET /api/v1/me": () => ADMIN,
    "GET /health": () => ({ ok: true }),
  });
  renderApp("/crm");
  expect(await screen.findByText("Sign in to continue")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "admin@altria.local" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw12345678" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  expect(screen.getByText("Maria CRM")).toBeInTheDocument();
  expect(localStorage.getItem("maria.token")).toBe("tok");
  const login = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/v1/auth/login"));
  expect(JSON.parse(String(login?.[1]?.body))).toEqual({
    email: "admin@altria.local",
    password: "pw12345678",
  });
  expect(await screen.findByText("API online")).toBeInTheDocument();
});

test("shows the login error from the API", async () => {
  mockApi({
    "POST /api/v1/auth/login": () =>
      new Response(JSON.stringify({ detail: "Invalid email or password" }), { status: 401 }),
  });
  renderApp("/login");
  fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "x@y.z" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "bad" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
});

test("an expired token logs the user out", async () => {
  localStorage.setItem("maria.token", "old");
  mockApi({
    "GET /api/v1/me": () => new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401 }),
  });
  renderApp("/crm/campaigns");
  await waitFor(() => expect(screen.getByText("Sign in to continue")).toBeInTheDocument());
  expect(localStorage.getItem("maria.token")).toBeNull();
});
