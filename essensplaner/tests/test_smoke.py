def test_settings_endpoint_reachable(client):
    res = client.get("/api/settings")
    assert res.status_code == 200
