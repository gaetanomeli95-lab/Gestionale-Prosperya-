import { describe, expect, it } from "vitest";
import { api, ApiError, setTenantId, setToken } from "./client";
import { apiError, jsonResponse, mockApi } from "../test/utils";

describe("api client", () => {
  it("sends bearer token and X-Tenant-Id when present", async () => {
    setToken("tok");
    setTenantId("tenant-1");
    const { calls } = mockApi([{ path: "/api/v1/companies", reply: jsonResponse({ ok: true }) }]);
    await api.get("/companies");
    const fetchMock = globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } };
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok");
    expect(headers["X-Tenant-Id"]).toBe("tenant-1");
    expect(calls[0].url).toBe("/api/v1/companies");
  });

  it("omits auth headers when logged out", async () => {
    mockApi([{ path: "/api/v1/health", reply: jsonResponse({}) }]);
    await api.get("/health");
    const fetchMock = globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } };
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers["X-Tenant-Id"]).toBeUndefined();
  });

  it("maps backend error envelopes to ApiError with code/status/message", async () => {
    mockApi([{ path: "/api/v1/x", reply: apiError(404, "not_found", "Azienda non trovata.") }]);
    const err = (await api.get("/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("Azienda non trovata.");
  });

  it("falls back to a generic error when the body is not JSON", async () => {
    mockApi([{ path: "/api/v1/boom", reply: new Response("<html>502</html>", { status: 502 }) }]);
    const err = (await api.get("/boom").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    expect(err.code).toBe("unknown");
  });

  it("returns undefined for 204", async () => {
    mockApi([{ method: "DELETE", path: "/api/v1/things/1", reply: new Response(null, { status: 204 }) }]);
    expect(await api.del("/things/1")).toBeUndefined();
  });
});
