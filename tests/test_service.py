"""Tests for the service module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hikresetpasswd.service import (
    _extract_key_from_response,
    _extract_serial_from_url,
    _find_redirect_urls,
    _looks_like_device_data,
    generate_key_offline,
    generate_key_offline_v2,
    parse_sadp_device_file,
    process_qr_content,
    process_sadp_device_file,
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


# ---------------------------------------------------------------------------
# New tests for URL serial extraction, offline fallback, WeChat redirect
# ---------------------------------------------------------------------------



class TestExtractSerialFromUrl:
    def test_plain_sn_param(self):
        url = "https://tool.hikvision.com/reset?sn=DS-2CD2T45G0P-I&date=20240315"
        serial, date_str = _extract_serial_from_url(url)
        assert serial == "DS-2CD2T45G0P-I"
        assert date_str == "20240315"

    def test_serial_number_camel_case_param(self):
        url = "https://hikvision.com/reset?serialNumber=DS-7908HQH-SH&date=2024-03-15"
        serial, date_str = _extract_serial_from_url(url)
        assert serial == "DS-7908HQH-SH"
        assert date_str == "20240315"

    def test_serial_in_url_path(self):
        url = "https://hikvision.com/reset/DS-2CD2T45G0P-I/key"
        serial, date_str = _extract_serial_from_url(url)
        assert serial == "DS-2CD2T45G0P-I"

    def test_base64_encoded_json_param(self):
        import base64
        import json
        payload = json.dumps({"sn": "DS-7908HQH-SH", "date": "20240315"})
        encoded = base64.b64encode(payload.encode()).decode()
        url = f"https://hikvision.com/reset?data={encoded}"
        serial, date_str = _extract_serial_from_url(url)
        assert serial == "DS-7908HQH-SH"
        assert date_str == "20240315"

    def test_no_serial_returns_none(self):
        url = "https://hikvision.com/reset?token=abc123"
        serial, date_str = _extract_serial_from_url(url)
        assert serial is None

    def test_invalid_url_returns_none(self):
        serial, date_str = _extract_serial_from_url("not-a-url")
        assert serial is None

    def test_date_hyphenated_normalised(self):
        url = "https://hikvision.com/reset?sn=DS-2CD2T45G0P-I&date=2024-03-15"
        serial, date_str = _extract_serial_from_url(url)
        assert date_str == "20240315"

    def test_device_serial_param(self):
        url = "https://hikvision.com/reset?deviceSerial=DS-2CD2T45G0P-I&startTime=20240315"
        serial, date_str = _extract_serial_from_url(url)
        assert serial == "DS-2CD2T45G0P-I"
        assert date_str == "20240315"


class TestFindRedirectUrls:
    def test_finds_href_url(self):
        from urllib.parse import urlparse
        html = '<a href="https://mp.weixin.qq.com/s?abc=def">click</a>'
        urls = _find_redirect_urls(html)
        assert any(urlparse(u).hostname == "mp.weixin.qq.com" for u in urls)

    def test_finds_js_location(self):
        from urllib.parse import urlparse
        js = "window.location.href = 'https://mp.weixin.qq.com/a/~XYZ';"
        urls = _find_redirect_urls(js)
        assert any(urlparse(u).hostname == "mp.weixin.qq.com" for u in urls)

    def test_finds_json_url(self):
        from urllib.parse import urlparse
        json_str = '{"url": "https://service.hikvision.com/key?token=abc123token"}'
        urls = _find_redirect_urls(json_str)
        assert any(urlparse(u).hostname == "service.hikvision.com" for u in urls)

    def test_empty_content_returns_empty_list(self):
        assert _find_redirect_urls("no urls here") == []

    def test_deduplicates_same_url(self):
        html = '<a href="https://hikvision.com/reset">A</a><a href="https://hikvision.com/reset">B</a>'
        urls = _find_redirect_urls(html)
        assert urls.count("https://hikvision.com/reset") == 1


class TestOfflineFallbackOn403:
    @pytest.mark.asyncio
    async def test_403_with_serial_in_url_generates_key(self):
        """When URL returns 403 but serial is in URL params, offline key should be generated."""
        import httpx
        url = "https://hikvision.com/reset?sn=DS-2CD2T45G0P-I&date=20240315"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "403", request=MagicMock(), response=mock_response
                )
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key is not None
            assert len(result.key) == 8
            assert result.method == "offline_from_url"
            assert "DS-2CD2T45G0P-I" in (result.error or "")

    @pytest.mark.asyncio
    async def test_403_without_serial_returns_error(self):
        """When URL returns 403 and no serial in URL, error should be returned."""
        import httpx
        url = "https://hikvision.com/reset?token=opaquetoken"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "403", request=MagicMock(), response=mock_response
                )
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key is None
            assert result.error is not None
            assert "403" in result.error

    @pytest.mark.asyncio
    async def test_network_error_with_serial_in_url_generates_key(self):
        """Network error + serial in URL params → offline key generated."""
        import httpx
        url = "https://hikvision.com/reset?sn=DS-7908HQH-SH&date=20240315"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.RequestError("Connection timeout")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key is not None
            assert result.method == "offline_from_url"


class TestWeChatRedirectSupport:
    @pytest.mark.asyncio
    async def test_wechat_url_allowed(self):
        """WeChat URLs (weixin.qq.com) should be fetchable."""
        url = "https://mp.weixin.qq.com/s?__biz=abc&key=test"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.text = '{"key": "WECHAT123"}'
            mock_response.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key == "WECHAT123"
            assert result.method == "url_fetch"

    @pytest.mark.asyncio
    async def test_hikvision_page_with_wechat_secondary_url(self):
        """When Hikvision page embeds a WeChat URL, the secondary URL should be fetched."""
        hikvision_url = "https://hikvision.com/reset?token=abc"
        wechat_url = "https://mp.weixin.qq.com/s?__biz=xyz&key=somekey123"

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            from urllib.parse import urlparse as _up
            hostname = _up(url).hostname or ""
            if hostname == "hikvision.com":
                # First call: Hikvision page with embedded WeChat URL
                mock_resp.text = f'<html><a href="{wechat_url}">点击获取密钥</a></html>'
            else:
                # Second call: WeChat page with the key
                mock_resp.text = '{"key": "WXKEY123"}'
            return mock_resp

        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(hikvision_url)
            assert result.key == "WXKEY123"
            assert result.method == "url_fetch_via_redirect"
            assert call_count == 2


# ---------------------------------------------------------------------------
# Tests for SADP device characteristic file parsing
# ---------------------------------------------------------------------------



class TestParseSadpDeviceFile:
    def test_parses_basic_xml(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<ProbeMatchList>
  <ProbeMatch>
    <DeviceSerial>DS-2CD2T45G0P-I20190101XXXX</DeviceSerial>
    <BootTime>2024-03-15</BootTime>
    <SoftwareVersion>V5.6.5</SoftwareVersion>
    <DeviceDescription>DS-2CD2T45G0P-I</DeviceDescription>
    <IPv4Address>192.168.1.64</IPv4Address>
  </ProbeMatch>
</ProbeMatchList>"""
        devices = parse_sadp_device_file(xml)
        assert len(devices) == 1
        assert devices[0]["serial"] == "DS-2CD2T45G0P-I20190101XXXX"
        assert devices[0]["date"] == "20240315"
        assert devices[0]["version"] == "V5.6.5"

    def test_parses_multiple_devices(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
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
        devices = parse_sadp_device_file(xml)
        assert len(devices) == 2
        assert devices[0]["serial"] == "DS-2CD2T45G0P-I20190101AAA"
        assert devices[1]["serial"] == "DS-7908HQH-SH20200101BBB"

    def test_no_device_serial_raises_error(self):
        xml = """<ProbeMatchList><ProbeMatch><SoftwareVersion>V1.0</SoftwareVersion></ProbeMatch></ProbeMatchList>"""
        with pytest.raises(ValueError, match="No device information"):
            parse_sadp_device_file(xml)

    def test_invalid_xml_raises_error(self):
        with pytest.raises(ValueError, match="Invalid XML"):
            parse_sadp_device_file("not xml at all!!!<<>>")

    def test_empty_xml_raises_error(self):
        with pytest.raises(ValueError):
            parse_sadp_device_file("<ProbeMatchList></ProbeMatchList>")

    def test_date_without_hyphens(self):
        xml = """<ProbeMatchList>
  <ProbeMatch>
    <DeviceSerial>DS-TEST12345</DeviceSerial>
    <BootTime>20240315</BootTime>
  </ProbeMatch>
</ProbeMatchList>"""
        devices = parse_sadp_device_file(xml)
        assert devices[0]["date"] == "20240315"

    def test_device_serial_tag_alternative(self):
        xml = """<ProbeMatchList>
  <ProbeMatch>
    <SerialNumber>DS-TEST12345</SerialNumber>
    <BootTime>2024-03-15</BootTime>
  </ProbeMatch>
</ProbeMatchList>"""
        devices = parse_sadp_device_file(xml)
        assert devices[0]["serial"] == "DS-TEST12345"


class TestProcessSadpDeviceFile:
    @pytest.mark.asyncio
    async def test_generates_key_from_xml(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<ProbeMatchList>
  <ProbeMatch>
    <DeviceSerial>DS-2CD2T45G0P-I20190101XXXX</DeviceSerial>
    <BootTime>2024-03-15</BootTime>
  </ProbeMatch>
</ProbeMatchList>"""
        results = await process_sadp_device_file(xml)
        assert len(results) == 1
        assert results[0].key is not None
        assert len(results[0].key) == 8
        assert results[0].method == "offline_v1_from_file"

    @pytest.mark.asyncio
    async def test_invalid_xml_returns_error_result(self):
        results = await process_sadp_device_file("not valid xml")
        assert len(results) == 1
        assert results[0].key is None
        assert results[0].error is not None

    @pytest.mark.asyncio
    async def test_uses_today_date_when_no_boot_time(self):
        xml = """<ProbeMatchList>
  <ProbeMatch>
    <DeviceSerial>DS-2CD2T45G0P-I20190101XXXX</DeviceSerial>
  </ProbeMatch>
</ProbeMatchList>"""
        results = await process_sadp_device_file(xml)
        assert results[0].key is not None
        assert results[0].method == "offline_v1_from_file"


class TestGenerateKeyOfflineV2:
    @pytest.mark.asyncio
    async def test_generates_key_from_serial_and_verify_code(self):
        result = await generate_key_offline_v2("DS-2CD2T45G0P-I", "ABCD1234")
        assert result.key is not None
        assert len(result.key) == 8
        assert result.method == "offline_v2"

    @pytest.mark.asyncio
    async def test_empty_serial_returns_error(self):
        result = await generate_key_offline_v2("", "ABCD1234")
        assert result.key is None
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_empty_verify_code_returns_error(self):
        result = await generate_key_offline_v2("DS-2CD2T45G0P-I", "")
        assert result.key is None
        assert result.error is not None


class TestSadpQrMultilineFormat:
    """Tests for the multi-line SADP QR code format parsing."""

    @pytest.mark.asyncio
    async def test_qr_with_date_uses_v1(self):
        content = "B:DS-7908HQH-SH12345678\nDate:20240315"
        result = await process_qr_content(content)
        assert result.key is not None
        assert result.method == "offline_v1"

    @pytest.mark.asyncio
    async def test_qr_with_verify_code_uses_v2(self):
        content = "B:DS-7908HQH-SH12345678\nDate:20240315\nVerifyCode:ABCD1234"
        result = await process_qr_content(content)
        assert result.key is not None
        assert result.method == "offline_v2"

    @pytest.mark.asyncio
    async def test_qr_verify_code_takes_priority_over_date(self):
        """When both date and verify_code are present, v2 (verify_code) takes priority."""
        content = "B:DS-2CD2T45G0P-I12345\nDate:20240315\nVerifyCode:TESTCODE"
        result = await process_qr_content(content)
        assert result.method == "offline_v2"


class TestWeChat403ErrorMessages:
    """Verify that 403 errors no longer suggest using WeChat browser."""

    @pytest.mark.asyncio
    async def test_403_error_no_wechat_browser_suggestion(self):
        """403 error message should guide to offline tab, not WeChat browser."""
        import httpx
        url = "https://hikvision.com/reset?token=opaquetoken"
        with patch("hikresetpasswd.service.httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "403", request=MagicMock(), response=mock_response
                )
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await process_qr_content(url)
            assert result.key is None
            # Should NOT suggest "WeChat browser on mobile"
            assert "WeChat browser on a mobile device in China" not in (result.error or "")
            # Should guide to offline tab
            assert "Offline Key Generation" in (result.error or "") or "offline" in (result.error or "").lower()
