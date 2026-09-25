import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import LoginPage from "./LoginPage";
import { ADMIN_USER, apiError, jsonResponse, mockApi, renderApp } from "../test/utils";

function Shell() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<h1>Dashboard</h1>} />
    </Routes>
  );
}

describe("LoginPage", () => {
  it("logs in with valid credentials, stores the token and navigates home", async () => {
    const { calls } = mockApi([
      { method: "POST", path: "/api/v1/auth/login", reply: jsonResponse({ access_token: "tok-123", user: ADMIN_USER }) },
    ]);
    renderApp(<Shell />, { route: "/login" });

    await userEvent.type(screen.getByLabelText(/email/i), "admin@prosperya.it");
    await userEvent.type(screen.getByLabelText(/password/i), "prosperya-admin-dev");
    await userEvent.click(screen.getByRole("button", { name: /accedi/i }));

    await screen.findByRole("heading", { name: "Dashboard" });
    expect(localStorage.getItem("prosperya.access_token")).toBe("tok-123");
    const login = calls.find((c) => c.url.endsWith("/auth/login"));
    expect(login?.body).toEqual({ email: "admin@prosperya.it", password: "prosperya-admin-dev" });
  });

  it("shows the server error message on wrong credentials and stays on the page", async () => {
    mockApi([
      { method: "POST", path: "/api/v1/auth/login", reply: apiError(401, "invalid_credentials", "Credenziali non valide.") },
    ]);
    renderApp(<Shell />, { route: "/login" });

    await userEvent.type(screen.getByLabelText(/email/i), "x@prosperya.it");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /accedi/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Credenziali non valide.");
    expect(localStorage.getItem("prosperya.access_token")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
  });

  it("disables the submit button while the request is in flight", async () => {
    let release!: () => void;
    const pending = new Promise<Response>((r) => { release = () => r(jsonResponse({ access_token: "t", user: ADMIN_USER })); });
    mockApi([{ method: "POST", path: "/api/v1/auth/login", reply: () => pending }]);
    renderApp(<Shell />, { route: "/login" });

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.it");
    await userEvent.type(screen.getByLabelText(/password/i), "pw");
    const btn = screen.getByRole("button", { name: /accedi/i });
    await userEvent.click(btn);
    await waitFor(() => expect(btn).toBeDisabled());
    release();
    await screen.findByRole("heading", { name: "Dashboard" });
  });
});
