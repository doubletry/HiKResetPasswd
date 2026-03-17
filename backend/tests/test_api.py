"""Tests for the FastAPI endpoints."""

import io
import pytest
import qrcode
from httpx import ASGITransport, AsyncClient
from PIL import Image
from unittest.mock import AsyncMock, MagicMock, patch

from backend.main import app


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
