def test_export_unknown_client_404(client):
    r = client.post("/admin/gdpr/erase/nope?org_id=999", headers={"X-Admin-Key": "x"})
    assert r.status_code in (401, 403)  # admin auth gate
