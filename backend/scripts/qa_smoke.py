"""Manual QA smoke run against a live server: exercises every API path the
UI uses, as staff and as a client-tenant user. Prints a PASS/FAIL table.
Usage: python scripts/qa_smoke.py [base_url]
"""
import json
import sys
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001") + "/api/v1"
results: list[tuple[str, str, str]] = []


def check(label, resp, expect=(200, 201, 204)):
    ok = resp.status_code in expect
    detail = "" if ok else resp.text[:160]
    results.append(("PASS" if ok else "FAIL", f"{resp.request.method} {label}", f"{resp.status_code} {detail}"))
    return resp


def login(c, email, pwd):
    r = c.post(f"{BASE}/auth/login", json={"email": email, "password": pwd})
    check(f"login {email}", r)
    return {"Authorization": f"Bearer {r.json()['access_token']}"} if r.status_code == 200 else {}


def run_as(c, h, tag):
    g = lambda p, **kw: check(f"[{tag}] {p}", c.get(f"{BASE}{p}", headers=h), **kw)  # noqa: E731
    g("/auth/me")
    g("/dashboard")
    g("/companies?page=1&page_size=25")
    g("/contacts?page=1&page_size=25")
    g("/leads?page=1&page_size=25")
    g("/opportunities?page=1&page_size=25")
    g("/service-lines")
    g("/service-lines/pipeline-stages")
    g("/tasks?page=1&page_size=25")
    g("/users?page=1&page_size=25")
    g("/search?q=demo")
    g("/audit?page=1&page_size=25")
    g("/billing/invoices?page=1&page_size=25")
    g("/billing/overview")
    g("/billing/provider", expect=(200, 403))
    g("/management/hub?year=2026&through_month=6")

    # full CRUD flow inside own tenant
    suffix = uuid.uuid4().hex[:6]
    r = check(f"[{tag}] /companies", c.post(f"{BASE}/companies", headers=h, json={
        "legal_name": f"QA {tag} {suffix} S.r.l.", "vat_number": f"IT{uuid.uuid4().int % 10**11:011d}"}))
    if r.status_code != 201:
        return
    cid = r.json()["id"]
    g(f"/companies/{cid}")
    g(f"/companies/{cid}/completeness", expect=(200, 404))
    r = check(f"[{tag}] /contacts", c.post(f"{BASE}/contacts", headers=h, json={
        "first_name": "QA", "last_name": suffix, "email": f"qa-{suffix}@example.com",
        "company_ids": [cid]}))
    check(f"[{tag}] /notes", c.post(f"{BASE}/notes", headers=h, json={
        "entity_type": "company", "entity_id": cid, "body": "nota QA"}))
    g(f"/notes?entity_type=company&entity_id={cid}")
    g(f"/timeline/company/{cid}")
    check(f"[{tag}] /tasks", c.post(f"{BASE}/tasks", headers=h, json={
        "title": f"task QA {suffix}", "entity_type": "company", "entity_id": cid}))
    r = check(f"[{tag}] /leads", c.post(f"{BASE}/leads", headers=h, json={
        "company_name": f"Lead QA {suffix}", "contact_name": "Mario Rossi",
        "email": f"lead-{suffix}@example.com", "source": "website"}))
    if r.status_code == 201:
        lid = r.json()["id"]
        check(f"[{tag}] /leads/{{id}}/convert", c.post(f"{BASE}/leads/{lid}/convert", headers=h,
                                                     json={"create_opportunity": True}))
    stages = c.get(f"{BASE}/service-lines/pipeline-stages", headers=h).json()
    if stages:
        r = check(f"[{tag}] /opportunities", c.post(f"{BASE}/opportunities", headers=h, json={
            "title": f"Opp QA {suffix}", "company_id": cid, "stage_id": stages[0]["id"],
            "expected_value_eur": 1000}))
        if r.status_code == 201 and len(stages) > 1:
            check(f"[{tag}] /opportunities/{{id}}/move", c.post(
                f"{BASE}/opportunities/{r.json()['id']}/move", headers=h, json={"stage_id": stages[1]["id"]}))
    else:
        results.append(("WARN", f"[{tag}] pipeline", "tenant has NO pipeline stages -> pipeline/kanban unusable"))
    r = check(f"[{tag}] /billing/invoices", c.post(f"{BASE}/billing/invoices", headers=h, json={
        "company_id": cid, "lines": [{"description": "Consulenza", "quantity": 1, "unit_price": 100, "vat_rate": 22}]}))
    g(f"/management/companies/{cid}/overview?year=2026&through_month=6")
    check(f"[{tag}] /assistant chat", c.post(f"{BASE}/assistant/companies/{cid}/chat", headers=h,
                                           json={"message": "Riepilogo ricavi", "year": 2026, "through_month": 6}))


def main():
    with httpx.Client(timeout=30) as c:
        admin = login(c, "admin@prosperya.it", "prosperya-admin-dev")
        run_as(c, admin, "admin")
        client = login(c, "cliente@demo.example", "prosperya-client-dev")
        if client:
            run_as(c, client, "client")
            # cross-tenant: client must never see admin's company
            admin_companies = c.get(f"{BASE}/companies?page_size=1", headers=admin).json()["items"]
            if admin_companies:
                r = c.get(f"{BASE}/companies/{admin_companies[0]['id']}", headers=client)
                results.append(("PASS" if r.status_code == 404 else "FAIL",
                                "[client] cross-tenant company detail", f"{r.status_code} (expected 404)"))
    width = max(len(r[1]) for r in results)
    for status, label, detail in results:
        print(f"{status:4} {label:<{width}}  {detail}")
    fails = [r for r in results if r[0] != "PASS"]
    print(f"\n{len(results) - len(fails)}/{len(results)} passed, {len(fails)} issues")
    if fails:
        print(json.dumps([f"{f[1]}: {f[2]}" for f in fails], indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
