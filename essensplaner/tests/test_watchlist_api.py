def test_watchlist_crud(client):
    res = client.post("/api/watchlist", json={"name": "Mehl", "unit": "kg"})
    assert res.status_code == 200
    item = res.json()
    assert item["name"] == "Mehl"

    res = client.get("/api/watchlist")
    assert res.status_code == 200
    assert len(res.json()) == 1

    res = client.delete(f"/api/watchlist/{item['id']}")
    assert res.status_code == 200
    assert client.get("/api/watchlist").json() == []


def test_remove_unknown_watchlist_item_returns_404(client):
    res = client.delete("/api/watchlist/9999")
    assert res.status_code == 404
