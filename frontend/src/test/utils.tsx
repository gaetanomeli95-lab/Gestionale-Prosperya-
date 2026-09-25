/**
 * Test helpers. Tests target roles/labels/accessible names so they survive
 * the visual redesign (Phase H) — never CSS classes or DOM nesting.
 */
import type { ReactElement } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../auth/AuthContext";
import { vi } from "vitest";

/** JSON response helper for the mocked global fetch. */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** API-shaped error body as produced by the backend error handlers. */
export function apiError(status: number, code: string, message: string): Response {
  return jsonResponse({ error: { code, message, details: {} } }, status);
}

type MockReq = { method: string; url: string; body: unknown };
type Route = {
  method?: string;
  path: string | RegExp;
  reply: Response | ((req: MockReq) => Response | Promise<Response>);
};

/**
 * Install a tiny route table on the mocked fetch. Unmatched calls fail loudly
 * so a test never silently passes on a missing stub.
 */
export function mockApi(routes: Route[]) {
  const calls: MockReq[] = [];
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const method = (init?.method ?? "GET").toUpperCase();
      let body: unknown = undefined;
      if (init?.body) {
        try { body = JSON.parse(init.body as string); } catch { body = init.body; }
      }
      const req: MockReq = { method, url, body };
      calls.push(req);
      const hit = routes.find((r) =>
        (r.method ?? "GET").toUpperCase() === method &&
        (typeof r.path === "string" ? url.endsWith(r.path) : r.path.test(url)));
      if (!hit) {
        return apiError(599, "unmocked", `No mock for ${method} ${url}`);
      }
      // Relative URLs cannot be wrapped in `new Request()` under Node — pass a plain record.
      return typeof hit.reply === "function" ? hit.reply(req) : hit.reply.clone();
    },
  );
  return { calls };
}

export const ADMIN_USER = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "admin@prosperya.it",
  full_name: "Admin Demo",
  role: "admin",
  is_active: true,
  tenant_id: "00000000-0000-0000-0000-0000000000aa",
};

/** Render inside router + query + auth providers, optionally pre-authenticated. */
export function renderApp(ui: ReactElement, opts: RenderOptions & { route?: string; token?: string } = {}) {
  if (opts.token) localStorage.setItem("prosperya.access_token", opts.token);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={[opts.route ?? "/"]}>{ui}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
    opts,
  );
}
