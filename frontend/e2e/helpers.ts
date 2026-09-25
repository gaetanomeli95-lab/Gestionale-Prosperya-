import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const ADMIN = { email: "admin@prosperya.it", password: "prosperya-admin-dev" };
export const API = "http://127.0.0.1:8000/api/v1";

/** First navigation may be aborted by Vite's cold dependency optimisation
 *  (it triggers a full reload). Retry once instead of failing the flow. */
export async function gotoStable(page: Page, url: string) {
  try {
    await page.goto(url, { waitUntil: "domcontentloaded" });
  } catch (e) {
    if (!String(e).includes("ERR_ABORTED")) throw e;
    await page.waitForTimeout(1500);
    await page.goto(url, { waitUntil: "domcontentloaded" });
  }
}

/** Log in through the real UI (accessible labels, not selectors). */
export async function loginViaUi(page: Page, creds = ADMIN) {
  await gotoStable(page, "/login");
  await page.getByLabel(/email/i).fill(creds.email);
  await page.getByLabel(/password/i).fill(creds.password);
  await page.getByRole("button", { name: /accedi/i }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}

/** API token for setup steps that the UI does not expose yet. */
export async function apiToken(request: APIRequestContext, creds = ADMIN): Promise<string> {
  const r = await request.post(`${API}/auth/login`, { data: creds });
  expect(r.ok()).toBeTruthy();
  return (await r.json()).access_token;
}

export function authHeaders(token: string) {
  return { Authorization: `Bearer ${token}` };
}

export const uniq = (prefix: string) => `${prefix} ${Date.now().toString(36).slice(-5).toUpperCase()}`;
