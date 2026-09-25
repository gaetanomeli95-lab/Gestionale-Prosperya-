/**
 * FLOW 4 — FUNDING
 * Company → programmes → eligibility match → assessment → application (funding practice)
 *   → requirements/checklist + deadline → linked operational practice (ADR-023)
 */
import { expect, test } from "@playwright/test";
import { API, apiToken, authHeaders, loginViaUi, uniq } from "./helpers";

test("Funding: match, assess, open an application linked to one operational practice", async ({ page, request }) => {
  const token = await apiToken(request);
  const h = authHeaders(token);
  await request.post(`${API}/funding/sync`, { headers: h });        // reference programmes (idempotent)

  const company = await (await request.post(`${API}/companies`, {
    headers: h, data: { legal_name: uniq("Agevolata Srl"), country: "IT", region: "Sicilia", employee_count: 12 },
  })).json();

  // programmes are visible in the UI
  await loginViaUi(page);
  await page.goto("/funding");
  await expect(page.getByRole("heading", { name: /finanza agevolata/i })).toBeVisible();
  await page.getByRole("tab", { name: "Programmi" }).click();
  await expect(page.getByText(/Sabatini/i).first()).toBeVisible();

  // eligibility: the rules engine explains WHY, and "unknown" is a legitimate answer
  const match = await (await request.get(`${API}/funding/companies/${company.id}/match`, { headers: h })).json();
  const groups = Object.keys(match.groups ?? match);
  expect(groups).toEqual(expect.arrayContaining(["insufficient_data", "not_eligible"]));

  // assessment against a fixed-window programme
  const programmes = (await (await request.get(`${API}/funding/programmes`, { headers: h })).json()).programmes;
  const prog = programmes.find((p: { code: string }) => p.code === "TRANSIZIONE-5.0") ?? programmes[0];
  const version = (await (await request.get(`${API}/funding/programmes/${prog.id}`, { headers: h })).json()).versions[0];

  const assessment = await request.post(`${API}/funding/companies/${company.id}/assessments`, {
    headers: h, data: { version_id: version.id },
  });
  expect(assessment.status(), await assessment.text()).toBe(201);
  const a = await assessment.json();
  expect(a.engine_version).toBeTruthy();
  expect(Array.isArray(a.items)).toBe(true);                        // per-rule evidence

  // application = funding practice, opened directly by the professional
  const fp = await request.post(`${API}/funding/companies/${company.id}/practices`, {
    headers: h, data: { version_id: version.id },
  });
  expect(fp.status(), await fp.text()).toBe(201);
  const practice = await fp.json();
  expect(practice.status).toBe("draft");
  expect(practice.documents.length).toBeGreaterThan(0);            // checklist materialised
  expect(practice.practice_id).toMatch(/^[0-9a-f-]{36}$/);          // ADR-023 link

  // the generic operational practice exists, typed funding, with document blockers
  const generic = await (await request.get(`${API}/practices/${practice.practice_id}`, { headers: h })).json();
  expect(generic.practice_type).toBe("funding");
  expect(generic.external_ref).toBe(practice.id);
  expect(generic.blockers.some((b: { kind: string }) => b.kind === "missing_document")).toBe(true);

  // UI: the funding workspace for this company lists the application under Pratiche
  await page.goto(`/funding?company=${company.id}`);
  await page.getByRole("tab", { name: "Pratiche" }).click();
  // rows show the programme title (business label), never raw id prefixes
  expect(practice.programme_title).toBe(prog.title);
  await expect(page.getByRole("row", { name: new RegExp(prog.title.slice(0, 15)) })).toBeVisible();
  await expect(page.getByText(practice.id.slice(0, 8))).toHaveCount(0);
  // and the company page dossier shows exactly ONE operational practice (ADR-023)
  await page.goto(`/companies/${company.id}`);
  await page.getByRole("tab", { name: "Dossier" }).click();
  await expect(page.getByText(/Documenti mancanti \([1-9]\d*\)/)).toBeVisible();
  const dossier = await (await request.get(`${API}/practices/companies/${company.id}/dossier`, { headers: h })).json();
  expect(dossier.practices).toHaveLength(1);
  expect(dossier.practices[0].practice_type).toBe("funding");
});
