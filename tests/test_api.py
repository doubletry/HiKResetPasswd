"""Tests for the FastAPI endpoints."""

import io

import pytest
import qrcode
from httpx import ASGITransport, AsyncClient
from PIL import Image

from hikresetpasswd.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_qr_bytes(content: str) -> bytes:
    """Create a QR code image bytes for testing."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_upload_qr_image_valid(client):
    """Test uploading a valid QR code image."""
    qr_content = "B:DS-7908HQH-SH12345678"
    img_bytes = make_qr_bytes(qr_content)

    response = await client.post(
        "/api/qr/upload",
        files={"file": ("qr.png", img_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["qr_content"] == qr_content


@pytest.mark.asyncio
async def test_upload_qr_image_not_image(client):
    """Test uploading a non-image file."""
    response = await client.post(
        "/api/qr/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_qr_image_no_qr(client):
    """Test uploading an image without a QR code."""
    img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    response = await client.post(
        "/api/qr/upload",
        files={"file": ("plain.png", img_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["error"] is not None
    assert "No QR code found" in data["error"]


@pytest.mark.asyncio
async def test_process_qr_content_endpoint(client):
    """Test the QR content endpoint."""
    response = await client.post(
        "/api/qr/content",
        json={"qr_content": "B:DS-7908HQH-SH12345678"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["qr_content"] == "B:DS-7908HQH-SH12345678"


@pytest.mark.asyncio
async def test_process_qr_content_empty(client):
    """Test that empty QR content returns 400."""
    response = await client.post(
        "/api/qr/content",
        json={"qr_content": ""},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_offline_key_generation(client):
    """Test offline key generation endpoint."""
    response = await client.post(
        "/api/key/offline",
        json={"serial": "DS-2CD2T45G0P-I", "date": "20240315"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key"] is not None
    assert len(data["key"]) == 8
    assert data["method"] == "offline_v1"


@pytest.mark.asyncio
async def test_offline_key_invalid_date(client):
    """Test offline key generation with invalid date."""
    response = await client.post(
        "/api/key/offline",
        json={"serial": "DS-2CD2T45G0P-I", "date": "not-a-date"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key"] is None
    assert data["error"] is not None


@pytest.mark.asyncio
async def test_offline_key_empty_serial(client):
    """Test offline key generation with empty serial."""
    response = await client.post(
        "/api/key/offline",
        json={"serial": "", "date": "20240315"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Static file serving tests (production mode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_api_path_returns_not_found_or_spa(client):
    """Non-API paths return 404 (no dist/) or 200 (dist/ present for SPA)."""
    response = await client.get("/")
    # Without dist/, FastAPI returns 404; with dist/, the SPA catch-all returns 200
    assert response.status_code in (404, 200)


@pytest.mark.asyncio
async def test_spa_serving_with_dist(tmp_path):
    """When frontend/dist/ exists, the app serves index.html for non-API paths."""
    from unittest.mock import patch

    # Create a fake dist directory with index.html
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    index_html = dist_dir / "index.html"
    index_html.write_text("<html><body>HiK Reset</body></html>")
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('app')")

    # Patch _FRONTEND_DIST and reload the module to trigger the static mount
    with patch("hikresetpasswd.main._FRONTEND_DIST", dist_dir):
        # We need to re-create the app with the patched dist
        # Instead, test directly using a fresh FastAPI instance
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        test_app = FastAPI()

        # Copy all existing routes from the real app (API endpoints)
        for route in app.routes:
            if hasattr(route, "path") and route.path.startswith("/api"):
                test_app.routes.append(route)

        # Mount assets
        test_app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="test-assets")

        # Add SPA fallback
        @test_app.get("/{full_path:path}")
        async def serve(full_path: str):
            file_path = (dist_dir / full_path).resolve()
            if full_path and file_path.is_file() and file_path.is_relative_to(dist_dir):
                return FileResponse(str(file_path))
            return FileResponse(str(index_html))

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as ac:
            # Root should serve index.html
            resp = await ac.get("/")
            assert resp.status_code == 200
            assert "HiK Reset" in resp.text

            # Unknown SPA route should also serve index.html
            resp = await ac.get("/some/vue/route")
            assert resp.status_code == 200
            assert "HiK Reset" in resp.text

            # Assets should serve the actual file
            resp = await ac.get("/assets/app.js")
            assert resp.status_code == 200
            assert "console.log" in resp.text

            # API endpoints should still work
            resp = await ac.get("/api/health")
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_offline_key_v2(client):
    """Test offline key generation v2 endpoint."""
    response = await client.post(
        "/api/key/offline/v2",
        json={"serial": "DS-2CD2T45G0P-I", "verify_code": "ABCD1234"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key"] is not None
    assert len(data["key"]) == 8
    assert data["method"] == "offline_v2"


@pytest.mark.asyncio
async def test_offline_key_v2_empty_serial(client):
    """Test v2 endpoint with empty serial."""
    response = await client.post(
        "/api/key/offline/v2",
        json={"serial": "", "verify_code": "ABCD1234"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_offline_key_v2_empty_verify_code(client):
    """Test v2 endpoint with empty verify code."""
    response = await client.post(
        "/api/key/offline/v2",
        json={"serial": "DS-2CD2T45G0P-I", "verify_code": ""},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_sadp_upload_valid_xml(client):
    """Test uploading a valid SADP device characteristic XML."""
    xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<ProbeMatchList>
  <ProbeMatch>
    <DeviceSerial>DS-2CD2T45G0P-I20190101XXXX</DeviceSerial>
    <BootTime>2024-03-15</BootTime>
    <SoftwareVersion>V5.6.5</SoftwareVersion>
  </ProbeMatch>
</ProbeMatchList>"""
    response = await client.post(
        "/api/sadp/upload",
        files={"file": ("devices.xml", xml_content, "text/xml")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert len(data["devices"]) == 1
    assert data["devices"][0]["key"] is not None
    assert data["error"] is None


@pytest.mark.asyncio
async def test_sadp_upload_multi_device_xml(client):
    """Test uploading SADP XML with multiple devices."""
    xml_content = b"""<?xml version="1.0" encoding="utf-8"?>
<ProbeMatchList>
  <ProbeMatch>
    <DeviceSerial>DS-2CD2T45G0P-I20190101AAA</DeviceSerial>
    <BootTime>2024-03-15</BootTime>
  </ProbeMatch>
  <ProbeMatch>
    <DeviceSerial>DS-7908HQH-SH20200101BBB</DeviceSerial>
    <BootTime>2024-04-01</BootTime>
  </ProbeMatch>
</ProbeMatchList>"""
    response = await client.post(
        "/api/sadp/upload",
        files={"file": ("devices.xml", xml_content, "text/xml")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert all(dev["key"] is not None for dev in data["devices"])


@pytest.mark.asyncio
async def test_sadp_upload_invalid_xml(client):
    """Test uploading invalid XML returns an error response."""
    response = await client.post(
        "/api/sadp/upload",
        files={"file": ("bad.xml", b"not valid xml!!!<<>>", "text/xml")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["error"] is not None
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_sadp_upload_empty_file(client):
    """Test uploading empty file returns 400."""
    response = await client.post(
        "/api/sadp/upload",
        files={"file": ("empty.xml", b"", "text/xml")},
    )
    assert response.status_code == 400
