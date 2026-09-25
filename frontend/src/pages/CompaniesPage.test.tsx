import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import CompaniesPage from "./CompaniesPage";
import { ADMIN_USER, apiError, jsonResponse, mockApi, renderApp } from "../test/utils";

const ME = { method: "GET", path: "/api/v1/auth/me", reply: jsonResponse(ADMIN_USER) };

const page = (items: unknown[], total = items.length) =>
  jsonResponse({ items, total, page: 1, page_size: 25 });

const company = (over: Record<string, unknown> = {}) => ({
  id: "c-1", legal_name: "Azienda Demo Siciliana S.r.l.", vat_number: "IT01234567890",
  city: "Palermo", region: "Sicilia", status: "customer", size_band: "small", ...over,
});

describe("CompaniesPage — operational states (mission §37)", () => {
  it("renders the list with accessible table semantics", async () => {
    mockApi([ME, { path: /\/api\/v1\/companies\?/, reply: page([company(), company({ id: "c-2", legal_name: "Beta Srl" })]) }]);
    renderApp(<CompaniesPage />, { route: "/companies", token: "t" });

    expect(await screen.findByRole("heading", { name: "Aziende" })).toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(table).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Ragione sociale" })).toBeInTheDocument();
    expect(screen.getByText("Azienda Demo Siciliana S.r.l.")).toBeInTheDocument();
    expect(screen.getByText("Beta Srl")).toBeInTheDocument();
    expect(screen.getByText("2 anagrafiche")).toBeInTheDocument();
  });

  it("shows a loading status before data arrives", async () => {
    let release!: () => void;
    const pending = new Promise<Response>((r) => { release = () => r(page([])); });
    mockApi([ME, { path: /\/api\/v1\/companies\?/, reply: () => pending }]);
    renderApp(<CompaniesPage />, { route: "/companies", token: "t" });

    expect(await screen.findByRole("status")).toHaveTextContent(/caricamento/i);
    release();
    await screen.findByText("Nessuna azienda trovata.");
  });

  it("shows an explicit empty state, not a blank page", async () => {
    mockApi([ME, { path: /\/api\/v1\/companies\?/, reply: page([]) }]);
    renderApp(<CompaniesPage />, { route: "/companies", token: "t" });
    expect(await screen.findByText("Nessuna azienda trovata.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("surfaces a permission-denied error from the API as an alert", async () => {
    mockApi([ME, { path: /\/api\/v1\/companies\?/, reply: apiError(403, "forbidden", "Permessi insufficienti.") }]);
    renderApp(<CompaniesPage />, { route: "/companies", token: "t" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Permessi insufficienti.");
  });

  it("surfaces a server error as an alert instead of a raw traceback", async () => {
    mockApi([ME, { path: /\/api\/v1\/companies\?/, reply: apiError(500, "internal_error", "Errore interno.") }]);
    renderApp(<CompaniesPage />, { route: "/companies", token: "t" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Errore interno.");
    expect(screen.queryByText(/traceback/i)).not.toBeInTheDocument();
  });

  it("typing in the search box re-queries the API with q=", async () => {
    const { calls } = mockApi([ME, { path: /\/api\/v1\/companies\?/, reply: page([company()]) }]);
    renderApp(<CompaniesPage />, { route: "/companies", token: "t" });
    await screen.findByRole("table");
    await userEvent.type(screen.getByPlaceholderText(/cerca per nome/i), "Demo");
    await screen.findByRole("table");
    expect(calls.some((c) => /\/companies\?.*q=Demo/.test(c.url))).toBe(true);
  });

  it("opens the create dialog from the primary action", async () => {
    mockApi([ME, { path: /\/api\/v1\/companies\?/, reply: page([]) },
             { path: /\/api\/v1\/users\?/, reply: page([]) }]);
    renderApp(<CompaniesPage />, { route: "/companies", token: "t" });
    await screen.findByText("Nessuna azienda trovata.");
    await userEvent.click(screen.getByRole("button", { name: /nuova azienda/i }));
    expect(await screen.findByRole("dialog", { name: "Nuova azienda" })).toBeInTheDocument();
  });
});
