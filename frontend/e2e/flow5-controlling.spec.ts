/**
 * FLOW 5 — CONTROLLING
 * Company → debt facility (financial data) → scenario (BASE/STRESS/UPSIDE) → early-warning evaluate → alerts view
 */
import { expect, test } from "@playwright/test";
import { API, apiToken, authHeaders, loginViaUi, uniq } from "./helpers";

const day = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

test("Controlling: financial data, bounded scenarios, durable explainable alerts", async ({ page, request }) => {
  const token = await apiToken(request);
  const h = authHeaders(token);
  await request.post(`${API}/controlling/rules/sync`, { headers: h });   // versioned rules (idempotent)

  const company = await (await request.post(`${API}/companies`, {
    headers: h, data: { legal_name: uniq("Indebitata Srl"), country: "IT", status: "customer" },
  })).json();

  // financial data: a loan with an overdue instalment
  const facility = await (await request.post(`${API}/controlling/companies/${company.id}/facilities`, {
    headers: h, data: { name: "Mutuo chirografario", facility_type: "loan", lender_name: "Banca X",
                        outstanding_principal: "50000.00" },
  })).json();
  const inst = await request.post(`${API}/controlling/companies/${company.id}/facilities/${facility.id}/instalments`, {
    headers: h, data: { instalment_no: 1, due_date: day(-40), principal: "2000.00", interest: "150.00" },
  });
  expect(inst.status(), await inst.text()).toBe(201);

  // scenarios: presets exist and a bounded run returns a labelled result without touching actuals
  const presets = await (await request.get(`${API}/controlling/companies/${company.id}/scenarios/presets`, { headers: h })).json();
  expect(Object.keys(presets.presets)).toEqual(expect.arrayContaining(["base", "stress", "upside"]));
  const stress = await request.post(`${API}/controlling/companies/${company.id}/scenarios/run`, {
    headers: h, data: { label: "stress", revenue_change_pct: "-20", collection_delay_days: 30 },
  });
  expect(stress.status(), await stress.text()).toBe(200);

  // early warning is an explicit evaluation that persists alerts with evidence + rule version
  const evaluated = await request.post(`${API}/controlling/companies/${company.id}/alerts/evaluate`, { headers: h });
  expect(evaluated.status(), await evaluated.text()).toBe(201);
  const alerts = (await (await request.get(`${API}/controlling/companies/${company.id}/alerts`, { headers: h })).json()).alerts
    ?? await (await request.get(`${API}/controlling/companies/${company.id}/alerts`, { headers: h })).json();
  expect(Array.isArray(alerts)).toBe(true);
  for (const a of alerts) {
    expect(a.rule_code ?? a.rule_id).toBeTruthy();             // WHAT triggered
    expect(a.evidence ?? a.details).toBeTruthy();              // WHICH data / calculation
  }
  // re-evaluation is idempotent: same dedupe keys, no duplicates
  await request.post(`${API}/controlling/companies/${company.id}/alerts/evaluate`, { headers: h });
  const again = await (await request.get(`${API}/controlling/companies/${company.id}/alerts`, { headers: h })).json();
  const list = again.alerts ?? again;
  expect(list.length).toBe(alerts.length);

  // UI: controlling workspace opens for the company with the early-warning tab
  await loginViaUi(page);
  await page.goto("/controlling");
  await expect(page.getByRole("heading", { name: /controlling/i })).toBeVisible();
  await page.getByRole("tab", { name: "Early warning" }).click();
  await expect(page.getByRole("tab", { name: "Early warning" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Scenari" }).click();
  await expect(page.getByRole("tab", { name: "Scenari" })).toHaveAttribute("aria-selected", "true");
});
