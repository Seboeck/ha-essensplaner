def test_artikel_images_mount_serves_files(client, tmp_path):
    import artikel_images
    (artikel_images.ARTIKEL_IMAGES_DIR / "1.jpg").write_bytes(b"fake")
    res = client.get("/artikel-images/1.jpg")
    assert res.status_code == 200
    assert res.content == b"fake"
