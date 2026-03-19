"""Tests for the service module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hikresetpasswd.service import (
    _extract_key_from_response,
    _find_redirect_urls,
    _is_allowed_domain,
    _is_waf_response,
    _looks_like_device_data,
    _looks_like_sadp_challenge,
    generate_key_offline,
    process_qr_content,
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
        assert "not an allowed domain" in result.error

    @pytest.mark.asyncio
    async def test_internal_ip_url_blocked(self):
        """Internal IP addresses should be blocked."""
        url = "http://192.168.1.1/admin"
        result = await process_qr_content(url)
        assert result.key is None
        assert result.error is not None
        assert "not an allowed domain" in result.error

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
        assert "not an allowed domain" in result.error

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

    @pytest.mark.asyncio
    async def test_wechat_domain_allowed(self):
        """WeChat URLs (mp.weixin.qq.com) should be allowed for SADP scan flow."""
        url = "https://mp.weixin.qq.com/s?__biz=test&mid=123"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.text = '{"key": "WXKEY456"}'
            mock_response.raise_for_status = MagicMock()
            mock_response.url = url
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key == "WXKEY456"


class TestIsAllowedDomain:
    def test_hikvision_com(self):
        assert _is_allowed_domain("hikvision.com") is True

    def test_subdomain_hikvision(self):
        assert _is_allowed_domain("servicewechat.hikvision.com") is True

    def test_wechat_domain(self):
        assert _is_allowed_domain("mp.weixin.qq.com") is True

    def test_evil_domain(self):
        assert _is_allowed_domain("evil.com") is False

    def test_bypass_domain(self):
        assert _is_allowed_domain("evil.hikvision.com.attacker.com") is False

    def test_hikiot_domain(self):
        assert _is_allowed_domain("open.hikiot.com") is True


class TestLooksLikeSadpChallenge:
    def test_qrc_format(self):
        assert _looks_like_sadp_challenge("QRC03010003abcdef1234") is True

    def test_sn_challenge_format(self):
        assert _looks_like_sadp_challenge(
            "SN:DS-7608NI-E2;DATE:2024-03-15;CHALLENGE:XXXX"
        ) is True

    def test_random_string_not_challenge(self):
        assert _looks_like_sadp_challenge("hello world") is False

    def test_url_not_challenge(self):
        assert _looks_like_sadp_challenge("https://hikvision.com") is False


class TestProcessSadpChallenge:
    @pytest.mark.asyncio
    async def test_challenge_with_serial_falls_back_to_offline(self):
        """When service endpoints are unreachable, fall back to offline keygen."""
        content = "SN:DS-7608NI-E2;DATE:2024-03-15;CHALLENGE:XXXXABCDEF"
        with patch("hikresetpasswd.service._try_hikvision_service_endpoints",
                    return_value=None):
            result = await process_qr_content(content)
            assert result.key is not None
            assert result.method == "offline_v1"
            assert "DS-7608NI-E2" in result.error

    @pytest.mark.asyncio
    async def test_challenge_without_serial_returns_error(self):
        """QRC format without extractable serial returns guidance error."""
        content = "QRC03010003somebinarydata"
        with patch("hikresetpasswd.service._try_hikvision_service_endpoints",
                    return_value=None):
            result = await process_qr_content(content)
            assert result.key is None
            assert result.method == "sadp_challenge"
            assert "WeChat" in result.error or "400-700-5998" in result.error


class TestExtractKeyFromJson:
    def test_simple_json_key(self):
        content = '{"key": "ABCD1234", "status": "ok"}'
        assert _extract_key_from_response(content) == "ABCD1234"

    def test_nested_data_key(self):
        content = '{"status": "ok", "data": {"securityCode": "NESTED1234"}}'
        assert _extract_key_from_response(content) == "NESTED1234"

    def test_chinese_field_name(self):
        content = '{"安全码": "CNKEY5678"}'
        assert _extract_key_from_response(content) == "CNKEY5678"


class TestWafDetection:
    def test_detects_waf_response(self):
        content = '<html>changePageElem云安全平台检测到您当前的访问行为存在异常</html>'
        assert _is_waf_response(content) is True

    def test_normal_response_not_waf(self):
        content = '<html><body>Normal page</body></html>'
        assert _is_waf_response(content) is False


class TestFindRedirectUrls:
    def test_extracts_js_location_href(self):
        content = 'window.location.href = "https://service.hikvision.com/reset?code=abc"'
        urls = _find_redirect_urls(content)
        assert "https://service.hikvision.com/reset?code=abc" in urls

    def test_extracts_meta_refresh(self):
        content = '<meta http-equiv="refresh" content="0;url=https://hikvision.com/go">'
        urls = _find_redirect_urls(content)
        assert "https://hikvision.com/go" in urls

    def test_ignores_non_url_strings(self):
        content = 'window.location.href = "relative/path.html"'
        urls = _find_redirect_urls(content)
        assert len(urls) == 0

    def test_deduplicates_urls(self):
        content = (
            'window.location.href = "https://hikvision.com/a"\n'
            'window.location = "https://hikvision.com/a"'
        )
        urls = _find_redirect_urls(content)
        assert urls.count("https://hikvision.com/a") == 1


class TestUrlRedirectFollowing:
    @pytest.mark.asyncio
    async def test_follows_redirect_and_extracts_key(self):
        """URL fetch finds JS redirect, follows it, and extracts key."""
        url = "https://service.hikvision.com/reset?token=abc"
        initial_html = (
            '<html><script>window.location.href = '
            '"https://service.hikvision.com/result?key=abc"</script></html>'
        )
        redirect_json = '{"key": "REDIRECTKEY1"}'

        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_initial_response = MagicMock()
            mock_initial_response.text = initial_html
            mock_initial_response.raise_for_status = MagicMock()
            mock_initial_response.url = url

            mock_redirect_response = MagicMock()
            mock_redirect_response.text = redirect_json
            mock_redirect_response.raise_for_status = MagicMock()
            mock_redirect_response.url = "https://service.hikvision.com/result?key=abc"

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=[mock_initial_response, mock_redirect_response]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key == "REDIRECTKEY1"
            assert result.method == "url_redirect"
