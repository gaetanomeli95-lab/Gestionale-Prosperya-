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
  // NOTE: form labels are not yet associated with inputs (a11y gap for Phase H);
  // locate fields by their visible label text scoped to the dialog.
  await dialog.locator(".field", { hasText: "Ragione sociale" }).getByRole("textbox").fill(name);
  await dialog.getByRole("button", { name: /crea azienda/i }).click();

  await expect(page).toHaveURL(/\/companies\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const companyId = page.url().split("/").pop()!;

  // contact + opportunity through the API (UI creates them from global pages)
  const token = await apiToken(request);
  const contact = await request.post(`${API}/contacts`, {
    headers: authHeaders(token),
    data: { first_name: "Mario", last_name: "Rossi", email: `mario.${Date.now()}@example.com`,
            company_id: companyId, relationship_role: "Titolare", is_primary: true },
  });
  expect(contact.status(), await contact.text()).toBe(201);

  const stages = await (await request.get(`${API}/service-lines/pipeline-stages`, { headers: authHeaders(token) })).json();
  const first = stages.find((s: { is_won: boolean; is_lost: boolean }) => !s.is_won && !s.is_lost);
  const opp = await request.post(`${API}/opportunities`, {
    headers: authHeaders(token),
    data: { company_id: companyId, title: uniq("Consulenza"), stage_id: first.id, expected_value_eur: 5000 },
  });
  expect(opp.status(), await opp.text()).toBe(201);

  // GAP (documented in PROJECT_STATE_AUDIT §12, Phase H): the company detail
  // "Contatti" tab is a placeholder pointing to the global Contacts page, so the
  // linked contact is verified there.
  await gotoStable(page, "/contacts");
  await expect(page.getByRole("heading", { name: "Contatti" })).toBeVisible();
  await page.getByPlaceholder(/cerca per nome/i).fill("Mario");
  await expect(page.getByRole("row", { name: /Mario/ })).toBeVisible();

  // and the pipeline shows the opportunity
  await gotoStable(page, "/pipeline");
  await expect(page.getByRole("heading", { name: "Pipeline commerciale" })).toBeVisible();
  await expect(page.getByText(/Consulenza/).first()).toBeVisible();
});
