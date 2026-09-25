/**
 * FLOW 3 — DOCUMENT OPERATIONS
 * Practice → client request → document upload → requirement fulfilled → validation → status
 */
import { expect, test } from "@playwright/test";
import { API, apiToken, authHeaders, loginViaUi, uniq } from "./helpers";

test("Documents: request, receive, validate — requirement status follows the evidence", async ({ page, request }) => {
  const token = await apiToken(request);
  const h = authHeaders(token);
  const company = await (await request.post(`${API}/companies`, {
    headers: h, data: { legal_name: uniq("Documentale Srl"), country: "IT" },
  })).json();
  const practice = await (await request.post(`${API}/practices/companies/${company.id}`, {
    headers: h, data: { title: uniq("Istruttoria"), practice_type: "generic" },
  })).json();

  // 1. requirement (missing) created from the Documents UI (Pre-H), + client request via API
  await loginViaUi(page);
  await page.goto("/documents");
  await page.getByLabel("Azienda").selectOption({ label: company.legal_name });
  const form = page.getByRole("form", { name: /nuovo requisito/i });
  await form.getByLabel(/tipo documento/i).selectOption("visura_camerale");
  await form.getByLabel(/descrizione/i).fill("Visura camerale");
  await form.getByLabel(/pratica/i).selectOption({ label: practice.title });
  await form.getByRole("button", { name: /aggiungi requisito/i }).click();
  await expect(page.getByRole("row", { name: /Visura camerale/ })).toBeVisible();
  const req = (await (await request.get(`${API}/documents/requirements/list`,
    { headers: h, params: { practice_id: practice.practice_id ?? practice.id } })).json()).requirements[0];
  expect(req.status).toBe("missing");
  expect(req.practice_id).toBe(practice.id);

  const cr = await request.post(`${API}/practices/companies/${company.id}/requests`, {
    headers: h, data: { item: "Visura camerale aggiornata", practice_id: practice.id,
                        due_at: new Date(Date.now() + 3 * 86_400_000).toISOString() },
  });
  expect(cr.status(), await cr.text()).toBe(201);

  // the practice is blocked by the missing document
  let detail = await (await request.get(`${API}/practices/${practice.id}`, { headers: h })).json();
  expect(detail.blockers.some((b: { kind: string; status: string }) => b.kind === "missing_document" && b.status === "open")).toBe(true);

  // 2. upload the document (multipart) and fulfil the requirement
  const up = await request.post(`${API}/documents/companies/${company.id}/upload`, {
    headers: h,
    multipart: {
      title: "Visura camerale 2026", type_code: "visura_camerale",
      file: { name: "visura.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 e2e visura") },
    },
  });
  expect(up.status(), await up.text()).toBe(201);
  const doc = await up.json();
  expect(doc.status).toBe("received");
  expect(doc.versions[0].checksum_sha256).toMatch(/^[0-9a-f]{64}$/);

  let ff = await (await request.post(`${API}/documents/requirements/${req.id}/fulfill`, {
    headers: h, data: { document_id: doc.id },
  })).json();
  expect(ff.status).toBe("received");              // requires validation → not yet satisfied

  // 3. validate the version → requirement validated → blocker resolved
  const val = await request.post(`${API}/documents/${doc.id}/versions/${doc.current_version_id}/validate`, {
    headers: h, data: { result: "validated" },
  });
  expect(val.status(), await val.text()).toBe(200);
  ff = await (await request.post(`${API}/documents/requirements/${req.id}/fulfill`, {
    headers: h, data: { document_id: doc.id },
  })).json();
  expect(ff.status).toBe("validated");

  detail = await (await request.get(`${API}/practices/${practice.id}`, { headers: h })).json();
  expect(detail.blockers.every((b: { status: string }) => b.status === "resolved")).toBe(true);

  // UI: the documents page lists the file with its status; dossier shows nothing missing
  await page.goto("/documents");
  await expect(page.getByRole("heading", { name: "Documenti" })).toBeVisible();
  await expect(page.getByText("Visura camerale 2026")).toBeVisible();
  await page.goto(`/companies/${company.id}`);
  await page.getByRole("tab", { name: "Dossier" }).click();
  await expect(page.getByText(/Documenti mancanti \(0\)/)).toBeVisible();
});
