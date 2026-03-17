"""Tests for the service module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hikresetpasswd.service import (
    ResetKeyResult,
    generate_key_offline,
    process_qr_content,
    _looks_like_device_data,
    _extract_key_from_response,
)


class TestLooksLikeDeviceData:
    def test_b_prefix_format(self):
        assert _looks_like_device_data("B:DS-7908HQH-SH12345") is True

    def test_ds_prefix(self):
        assert _looks_like_device_data("DS-2CD2T45G0P-I") is True

    def test_ds_prefix_lowercase(self):
        assert _looks_like_device_data("ds-2cd2t45g0p-i") is True

    def test_url_is_not_device_data(self):
        assert _looks_like_device_data("https://hikvision.com/reset") is False

    def test_random_string_is_not_device_data(self):
        assert _looks_like_device_data("hello world") is False


class TestExtractKeyFromResponse:
    def test_extracts_key_field(self):
        content = '{"status": "ok", "key": "ABCD1234"}'
        assert _extract_key_from_response(content) == "ABCD1234"

    def test_extracts_security_code(self):
        content = '{"securityCode": "EFGH5678"}'
        assert _extract_key_from_response(content) == "EFGH5678"

    def test_extracts_safe_code(self):
        content = '{"safeCode": "IJKL9012"}'
        assert _extract_key_from_response(content) == "IJKL9012"

    def test_extracts_chinese_security_code(self):
        content = "安全码：MNOP3456"
        assert _extract_key_from_response(content) == "MNOP3456"

    def test_returns_none_for_no_match(self):
        content = "no key here"
        assert _extract_key_from_response(content) is None

    def test_ignores_short_values(self):
        content = '{"key": "ab"}'
        assert _extract_key_from_response(content) is None


class TestProcessQRContent:
    @pytest.mark.asyncio
    async def test_processes_device_data(self):
        content = "B:DS-7908HQH-SH12345678"
        result = await process_qr_content(content)
        assert result.qr_content == content
        # Should attempt offline key generation
        assert result.method in ("offline_v1", "raw")

    @pytest.mark.asyncio
    async def test_processes_raw_content(self):
        content = "some random content"
        result = await process_qr_content(content)
        assert result.qr_content == content
        assert result.method == "raw"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_processes_url(self):
        url = "https://hikvision.com/reset?token=test123"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.text = '{"key": "TESTKEY1"}'
            mock_response.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key == "TESTKEY1"
            assert result.method == "url_fetch"

    @pytest.mark.asyncio
    async def test_url_network_error(self):
        import httpx
        url = "https://hikvision.com/reset?token=test123"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key is None
            assert result.error is not None
            assert "Network error" in result.error


class TestGenerateKeyOffline:
    @pytest.mark.asyncio
    async def test_generates_key_for_valid_inputs(self):
        result = await generate_key_offline("DS-2CD2T45G0P-I", "20240315")
        assert result.key is not None
        assert len(result.key) == 8
        assert result.method == "offline_v1"

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self):
        result = await generate_key_offline("DS-2CD2T45G0P-I", "not-a-date")
        assert result.key is None
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_accepts_hyphenated_date(self):
        result = await generate_key_offline("DS-2CD2T45G0P-I", "2024-03-15")
        assert result.key is not None
        assert len(result.key) == 8


class TestSSRFProtection:
    @pytest.mark.asyncio
    async def test_non_hikvision_url_blocked(self):
        """Non-Hikvision URLs should be blocked to prevent SSRF."""
        url = "https://evil.com/steal?data=something"
        result = await process_qr_content(url)
        assert result.key is None
        assert result.error is not None
        assert "not a known Hikvision domain" in result.error

    @pytest.mark.asyncio
    async def test_internal_ip_url_blocked(self):
        """Internal IP addresses should be blocked."""
        url = "http://192.168.1.1/admin"
        result = await process_qr_content(url)
        assert result.key is None
        assert result.error is not None
        assert "not a known Hikvision domain" in result.error

    @pytest.mark.asyncio
    async def test_file_scheme_blocked(self):
        """File scheme URLs should be blocked."""
        url = "file:///etc/passwd"
        result = await process_qr_content(url)
        assert result.key is None
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_hikvision_domain_allowed(self):
        """Hikvision domain URLs should be fetched."""
        url = "https://hikvision.com/reset?token=test123"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.text = '{"key": "SECUREKEY"}'
            mock_response.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key == "SECUREKEY"

    @pytest.mark.asyncio
    async def test_domain_bypass_blocked(self):
        """Domain bypass attempt like evil.hikvision.com.attacker.com should be blocked."""
        url = "https://evil.hikvision.com.attacker.com/steal"
        result = await process_qr_content(url)
        assert result.key is None
        assert result.error is not None
        assert "not a known Hikvision domain" in result.error

    @pytest.mark.asyncio
    async def test_subdomain_of_hikvision_allowed(self):
        """Legitimate subdomains of Hikvision domains should be allowed."""
        url = "https://service.hikvision.com/reset?token=abc"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.text = '{"key": "SUBKEY123"}'
            mock_response.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key == "SUBKEY123"
