import io


def _create_recipe(client):
    res = client.post("/api/recipes", json={"title": "Bildtest", "base_servings": 4, "ingredients": []})
    assert res.status_code == 200
    return res.json()["id"]


def test_upload_recipe_image_rejects_oversized_file(client, monkeypatch):
    import main as main_module
    monkeypatch.setattr(main_module, "MAX_UPLOAD_SIZE_BYTES", 10)  # winzige Grenze für den Test
    recipe_id = _create_recipe(client)

    file_bytes = b"x" * 100  # groesser als die gesetzte Grenze
    res = client.post(
        f"/api/recipes/{recipe_id}/image",
        files={"file": ("foto.jpg", io.BytesIO(file_bytes), "image/jpeg")},
    )
    assert res.status_code == 413


def test_upload_recipe_image_accepts_file_within_limit(client):
    recipe_id = _create_recipe(client)

    file_bytes = b"x" * 100
    res = client.post(
        f"/api/recipes/{recipe_id}/image",
        files={"file": ("foto.jpg", io.BytesIO(file_bytes), "image/jpeg")},
    )
    assert res.status_code == 200
    assert res.json()["image_path"] == f"/recipe-images/{recipe_id}.jpg"
