def test_lead_convert_creates_company_contact_opportunity(client, admin_headers):
    lead = client.post("/api/v1/leads", json={
        "company_name": "Convert Me S.r.l.",
        "contact_name": "Paolo Verdi",
        "email": "paolo@convertme.example",
        "source": "website",
        "estimated_value_eur": 5000,
    }, headers=admin_headers)
    assert lead.status_code == 201, lead.text
    lead_id = lead.json()["id"]

    r = client.post(f"/api/v1/leads/{lead_id}/convert", json={"create_opportunity": True},
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company_id"]
    assert body["contact_id"]
    assert body["opportunity_id"]
    assert body["lead"]["status"] == "converted"

    # second conversion blocked
    r2 = client.post(f"/api/v1/leads/{lead_id}/convert", json={}, headers=admin_headers)
    assert r2.status_code == 409


def test_opportunity_move_to_won(client, admin_headers):
    companies = client.get("/api/v1/companies?q=Demo", headers=admin_headers).json()["items"]
    company_id = companies[0]["id"]
    stages = client.get("/api/v1/service-lines/pipeline-stages", headers=admin_headers).json()
    first_stage = next(s for s in stages if not s["is_won"] and not s["is_lost"])
    won_stage = next(s for s in stages if s["is_won"])

    opp = client.post("/api/v1/opportunities", json={
        "title": "Move test", "company_id": company_id, "stage_id": first_stage["id"],
        "expected_value_eur": 1000,
    }, headers=admin_headers)
    assert opp.status_code == 201, opp.text
    opp_id = opp.json()["id"]

    r = client.post(f"/api/v1/opportunities/{opp_id}/move",
                    json={"stage_id": won_stage["id"]}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "won"
    assert r.json()["closed_at"]


def test_task_completion_sets_completed_at(client, admin_headers):
    t = client.post("/api/v1/tasks", json={"title": "Call demo client"},
                    headers=admin_headers)
    assert t.status_code == 201
    tid = t.json()["id"]
    r = client.patch(f"/api/v1/tasks/{tid}", json={"status": "done"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["completed_at"]


def test_rbac_readonly_cannot_write(client, admin_headers):
    # create a readonly user
    r = client.post("/api/v1/users", json={
        "email": "auditor@prosperya.it", "full_name": "Read Only",
        "password": "readonly-pass-1", "role": "readonly",
    }, headers=admin_headers)
    assert r.status_code == 201, r.text
    login = client.post("/api/v1/auth/login", json={
        "email": "auditor@prosperya.it", "password": "readonly-pass-1",
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # read works
    assert client.get("/api/v1/companies", headers=headers).status_code == 200
    # write is forbidden
    w = client.post("/api/v1/companies", json={"legal_name": "Nope S.r.l."}, headers=headers)
    assert w.status_code == 403


def test_global_search(client, admin_headers):
    r = client.get("/api/v1/search?q=Demo", headers=admin_headers)
    assert r.status_code == 200
    types = {h["type"] for h in r.json()["results"]}
    assert "company" in types


def test_dashboard_shape(client, admin_headers):
    r = client.get("/api/v1/dashboard", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    for key in ("open_opportunities", "pipeline_value_eur", "pipeline_by_stage",
                "my_open_tasks", "companies_total"):
        assert key in body


def test_timeline_records_events(client, admin_headers):
    created = client.post("/api/v1/companies", json={
        "legal_name": "Timeline Test S.r.l.",
    }, headers=admin_headers)
    cid = created.json()["id"]
    client.post("/api/v1/notes", json={
        "body": "Primo contatto telefonico", "entity_type": "company", "entity_id": cid,
    }, headers=admin_headers)
    r = client.get(f"/api/v1/timeline/company/{cid}", headers=admin_headers)
    assert r.status_code == 200
    types = {e["event_type"] for e in r.json()["items"]}
    assert "note.added" in types
    assert "company.created" in types


def test_notes_scoped_to_entity(client, admin_headers):
    companies = client.get("/api/v1/companies?q=Demo", headers=admin_headers).json()["items"]
    cid = companies[0]["id"]
    r = client.get(f"/api/v1/notes?entity_type=company&entity_id={cid}", headers=admin_headers)
    assert r.status_code == 200
    assert all(n["entity_id"] == cid for n in r.json()["items"])
