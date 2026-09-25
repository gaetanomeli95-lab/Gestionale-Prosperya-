/**
 * FLOW 1 â€” CRM
 * Login â†’ company list â†’ create company (dialog) â†’ company detail â†’ contact â†’ opportunity
 */
import { expect, test } from "@playwright/test";
import { API, apiToken, authHeaders, gotoStable, loginViaUi, uniq } from "./helpers";

test("CRM: login, create company from the UI, add contact and opportunity", async ({ page, request }) => {
  await loginViaUi(page);

  await gotoStable(page, "/companies");
  await expect(page.getByRole("heading", { name: "Aziende" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();

  // create company via the modal
  const name = uniq("E2E Impresa Srl");
  await page.getByRole("button", { name: /nuova azienda/i }).click();
  const dialog = page.getByRole("dialog", { name: "Nuova azienda" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel(/ragione sociale/i).fill(name);
  await dialog.getByLabel(/forma giuridica/i).fill("S.r.l.");
  await dialog.getByRole("button", { name: /crea azienda/i }).click();

  await expect(page).toHaveURL(/\/companies\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const companyId = page.url().split("/").pop()!;

  // contact created FROM the company "Contatti" tab (Pre-H: real tab, no longer a placeholder)
  await page.getByRole("tab", { name: "Contatti" }).click();
  await expect(page.getByText(/nessun contatto collegato/i)).toBeVisible();
  await page.getByRole("button", { name: /nuovo contatto/i }).click();
  const cdlg = page.getByRole("dialog", { name: "Nuovo contatto" });
  await cdlg.getByLabel(/^nome/i).fill("Mario");
  await cdlg.getByLabel(/cognome/i).fill("Rossi");
  await cdlg.getByLabel(/^email/i).fill(`mario.${Date.now()}@example.com`);
  await cdlg.getByLabel(/ruolo nell'azienda/i).fill("Titolare");
  await cdlg.getByLabel(/referente principale/i).check();
  await cdlg.getByRole("button", { name: "Crea" }).click();
  await expect(cdlg).toBeHidden();
  await expect(page.getByRole("row", { name: /Mario Rossi/ })).toBeVisible();
  await expect(page.getByText("1 contatto collegato")).toBeVisible();

  const token = await apiToken(request);
  const stages = await (await request.get(`${API}/service-lines/pipeline-stages`, { headers: authHeaders(token) })).json();
  const first = stages.find((s: { is_won: boolean; is_lost: boolean }) => !s.is_won && !s.is_lost);
  const opp = await request.post(`${API}/opportunities`, {
    headers: authHeaders(token),
    data: { company_id: companyId, title: uniq("Consulenza"), stage_id: first.id, expected_value_eur: 5000 },
  });
  expect(opp.status(), await opp.text()).toBe(201);

  // the global Contacts page (same domain, same API) sees the same person
  await gotoStable(page, "/contacts");
  await expect(page.getByRole("heading", { name: "Contatti" })).toBeVisible();
  await page.getByLabel(/cerca per nome/i).fill("Mario");
  await expect(page.getByRole("row", { name: /Mario Rossi/ })).toBeVisible();

  // and the pipeline shows the opportunity
  await gotoStable(page, "/pipeline");
  await expect(page.getByRole("heading", { name: "Pipeline commerciale" })).toBeVisible();
  await expect(page.getByText(/Consulenza/).first()).toBeVisible();
});
