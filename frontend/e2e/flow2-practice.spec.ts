/**
 * FLOW 2 — PRACTICE
 * Company → create practice (UI) → deadline → task → document requirement → dossier
 */
import { expect, test } from "@playwright/test";
import { API, apiToken, authHeaders, loginViaUi, uniq } from "./helpers";

test("Practice: open from the UI, add deadline (task) and a document requirement", async ({ page, request }) => {
  const token = await apiToken(request);
  const company = await (await request.post(`${API}/companies`, {
    headers: authHeaders(token), data: { legal_name: uniq("Pratica Srl"), country: "IT" },
  })).json();

  await loginViaUi(page);
  await page.goto("/practices");
  await expect(page.getByRole("heading", { name: "Pratiche" })).toBeVisible();

  // create through the real form: pick company, type title, submit.
  // The app shell also has a tenant <select>; scope to the one listing companies.
  const title = uniq("Bilancio annuale");
  const companySelect = page.locator("select").filter({ has: page.locator("option", { hasText: company.legal_name }) });
  await companySelect.selectOption({ label: company.legal_name });
  await page.getByPlaceholder(/nuova pratica/i).fill(title);
  await page.getByRole("button", { name: "Crea" }).click();
  const row = page.getByRole("row", { name: new RegExp(title) });
  await expect(row).toBeVisible();

  const practices = await (await request.get(`${API}/practices`, {
    headers: authHeaders(token), params: { company_id: company.id },
  })).json();
  const practice = practices.practices.find((p: { title: string }) => p.title === title);
  expect(practice).toBeTruthy();

  // deadline → operational task, from the UI (Pre-H: no longer API-only)
  const dueDate = new Date(Date.now() + 5 * 86_400_000).toISOString().slice(0, 10);
  await page.getByRole("button", { name: `Aggiungi scadenza a ${title}` }).click();
  const dlg = page.getByRole("dialog", { name: /scadenza/i });
  await dlg.getByLabel(/titolo/i).fill("Consegna bozza");
  await dlg.getByLabel(/data/i).fill(dueDate);
  await dlg.getByRole("button", { name: /crea scadenza/i }).click();
  await expect(dlg).toBeHidden();
  // exactly-once: the same deadline again updates instead of duplicating
  const d2 = await request.post(`${API}/practices/${practice.id}/deadlines`, {
    headers: authHeaders(token),
    data: { title: "Consegna bozza", due_at: `${dueDate}T12:00:00.000Z`, kind: "deadline" },
  });
  expect([200, 201]).toContain(d2.status());

  // document requirement attached to the practice
  const req = await request.post(`${API}/documents/companies/${company.id}/requirements`, {
    headers: authHeaders(token),
    data: { doc_type_code: "visura_camerale", label: "Visura camerale", practice_id: practice.id,
            mandatory: true, requires_validation: true },
  });
  expect(req.status(), await req.text()).toBe(201);

  // the dossier reads ONE canonical layer: 1 practice, 1 missing document, 1 deadline
  const dossier = await (await request.get(`${API}/practices/companies/${company.id}/dossier`,
    { headers: authHeaders(token) })).json();
  expect(dossier.practices).toHaveLength(1);
  expect(dossier.missing_documents).toHaveLength(1);
  expect(dossier.deadlines).toHaveLength(1);           // second identical deadline did NOT duplicate the task

  // UI: the deadline task is in the global operational queue, the missing
  // document in the company dossier
  await page.goto("/tasks");
  await expect(page.getByRole("heading", { name: /attivit/i })).toBeVisible();
  await expect(page.getByText("Consegna bozza").first()).toBeVisible();
  await page.goto(`/companies/${company.id}`);
  await page.getByRole("tab", { name: "Dossier" }).click();
  await expect(page.getByText(/Visura camerale/).first()).toBeVisible();
});
