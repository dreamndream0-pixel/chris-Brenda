"""SupabaseStorage request shapes (mirrors supabase storage-js StorageFileApi)."""
import httpx
import pytest

from services.core.storage import StorageError, SupabaseStorage

KEY = "embroidery/private/u1/p1/1/result.dst"


def make(handler):
    return SupabaseStorage("https://proj.supabase.co/", "service-key", "embroidery",
                           client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_put_and_get():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.method == "POST":
            return httpx.Response(200, json={"Key": "embroidery/private/u1/p1/1/result.dst"})
        return httpx.Response(200, content=b"DST")

    s = make(handler)
    checksum = s.put(KEY, b"DST")
    assert len(checksum) == 64 and s.get(KEY) == b"DST"
    up, down = seen
    assert up.url == "https://proj.supabase.co/storage/v1/object/embroidery/private/u1/p1/1/result.dst"
    assert up.headers["authorization"] == "Bearer service-key" and up.headers["apikey"] == "service-key"
    assert up.headers["x-upsert"] == "true" and up.content == b"DST"
    assert down.method == "GET" and down.url.path == "/storage/v1/object/embroidery/private/u1/p1/1/result.dst"


def test_missing_object_is_file_not_found():
    s = make(lambda req: httpx.Response(400, json={"error": "not_found"}))
    with pytest.raises(FileNotFoundError):
        s.get(KEY)
    assert s.exists(KEY) is False


def test_signed_download_url():
    def handler(req):
        assert req.url.path == "/storage/v1/object/sign/embroidery/private/u1/p1/1/result.dst"
        assert req.read() == b'{"expiresIn":300}'
        return httpx.Response(200, json={"signedURL": "/object/sign/embroidery/private/u1/p1/1/result.dst?token=abc"})

    url = make(handler).signed_download_url(KEY, "result.dst", 300)
    assert url == ("https://proj.supabase.co/storage/v1/object/sign/embroidery/private/u1/p1/1/result.dst"
                   "?token=abc&download=result.dst")


def test_signed_upload():
    def handler(req):
        assert req.method == "POST" and req.url.path == "/storage/v1/object/upload/sign/embroidery/private/u1/p1/uploads/x.png"
        return httpx.Response(200, json={"url": "/object/upload/sign/embroidery/private/u1/p1/uploads/x.png?token=t"})

    up = make(handler).signed_upload("embroidery/private/u1/p1/uploads/x.png", "image/png")
    assert up["url"].endswith("/storage/v1/object/upload/sign/embroidery/private/u1/p1/uploads/x.png?token=t")
    assert up["headers"] == {"content-type": "image/png", "x-upsert": "false"}


def test_errors_and_bad_keys():
    s = make(lambda req: httpx.Response(500))
    with pytest.raises(StorageError):
        s.put(KEY, b"x")
    with pytest.raises(ValueError):
        s.put("embroidery/../etc/passwd", b"x")
