"""Tests for the QR code decoder module."""

import io
import pytest
import qrcode
from PIL import Image

from hikresetpasswd.qr_decoder import decode_qr_from_bytes, QRCodeDecodeError


def make_qr_image_bytes(content: str, image_format: str = "PNG") -> bytes:
    """Helper to create a QR code image as bytes."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format=image_format)
    return buf.getvalue()


class TestDecodeQRFromBytes:
    def test_decode_simple_text(self):
        """Should decode a simple text QR code."""
        content = "Hello, World!"
        img_bytes = make_qr_image_bytes(content)
        result = decode_qr_from_bytes(img_bytes)
        assert result == content

    def test_decode_url(self):
        """Should decode a URL QR code."""
        url = "https://www.hikvision.com/cn/password-reset/?token=abc123"
        img_bytes = make_qr_image_bytes(url)
        result = decode_qr_from_bytes(img_bytes)
        assert result == url

    def test_decode_device_data(self):
        """Should decode Hikvision-style device data."""
        device_data = "B:DS-7908HQH-SH12345678"
        img_bytes = make_qr_image_bytes(device_data)
        result = decode_qr_from_bytes(img_bytes)
        assert result == device_data

    def test_decode_jpeg_image(self):
        """Should work with JPEG images."""
        content = "test content"
        img_bytes = make_qr_image_bytes(content, "JPEG")
        result = decode_qr_from_bytes(img_bytes)
        assert result == content

    def test_invalid_image_raises_error(self):
        """Invalid image bytes should raise QRCodeDecodeError."""
        with pytest.raises(QRCodeDecodeError, match="Cannot open image"):
            decode_qr_from_bytes(b"not an image")

    def test_image_without_qr_raises_error(self):
        """Image without QR code should raise QRCodeDecodeError."""
        # Create a plain white image without QR code
        img = Image.new("RGB", (100, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        with pytest.raises(QRCodeDecodeError, match="No QR code found"):
            decode_qr_from_bytes(img_bytes)

    def test_empty_bytes_raises_error(self):
        """Empty bytes should raise QRCodeDecodeError."""
        with pytest.raises(QRCodeDecodeError):
            decode_qr_from_bytes(b"")
