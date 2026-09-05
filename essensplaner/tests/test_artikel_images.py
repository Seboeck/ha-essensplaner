from unittest.mock import Mock, patch


def test_download_artikel_image_saves_file_and_returns_path(tmp_path, monkeypatch):
    import artikel_images
    monkeypatch.setattr(artikel_images, "ARTIKEL_IMAGES_DIR", tmp_path)

    fake_response = Mock()
    fake_response.headers = {"content-type": "image/jpeg"}
    fake_response.content = b"fake-image-bytes"
    fake_response.raise_for_status = Mock()

    with patch("artikel_images.httpx.get", return_value=fake_response):
        result = artikel_images.download_artikel_image(42, "https://example.invalid/img.jpg")

    assert result == "/artikel-images/42.jpg"
    assert (tmp_path / "42.jpg").read_bytes() == b"fake-image-bytes"


def test_download_artikel_image_returns_none_on_http_error(tmp_path, monkeypatch):
    import artikel_images
    import httpx
    monkeypatch.setattr(artikel_images, "ARTIKEL_IMAGES_DIR", tmp_path)

    with patch("artikel_images.httpx.get", side_effect=httpx.ConnectError("nope")):
        result = artikel_images.download_artikel_image(42, "https://example.invalid/img.jpg")

    assert result is None
