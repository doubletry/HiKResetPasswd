"""Tests for the SADP discovery module."""

import xml.etree.ElementTree as ET

from hikresetpasswd.sadp_discovery import (
    _build_probe_xml,
    _parse_sadp_response,
    check_firmware_support,
    parse_firmware_version,
)


class TestParseFirmwareVersion:
    def test_standard_format(self):
        assert parse_firmware_version("V5.2.5build 141201") == (5, 2, 5)

    def test_simple_format(self):
        assert parse_firmware_version("V7.3.0") == (7, 3, 0)

    def test_no_prefix(self):
        assert parse_firmware_version("5.3.0") == (5, 3, 0)

    def test_two_part_version(self):
        assert parse_firmware_version("V5.3") == (5, 3, 0)

    def test_lowercase_v(self):
        assert parse_firmware_version("v5.2.5") == (5, 2, 5)

    def test_empty_string(self):
        assert parse_firmware_version("") is None

    def test_no_version(self):
        assert parse_firmware_version("no version here") is None

    def test_complex_build_string(self):
        assert parse_firmware_version("V5.0, build 140714") == (5, 0, 0)


class TestCheckFirmwareSupport:
    def test_old_firmware_supported(self):
        supports, note = check_firmware_support("V5.2.5build 141201")
        assert supports is True
        assert "支持离线" in note or "supports offline" in note.lower()

    def test_threshold_firmware_not_supported(self):
        supports, note = check_firmware_support("V5.3.0")
        assert supports is False
        assert "不支持离线" in note or "NOT support" in note

    def test_new_firmware_not_supported(self):
        supports, note = check_firmware_support("V7.3.0")
        assert supports is False
        assert "不支持离线" in note or "NOT support" in note
        # Should include guidance for official channels
        assert "400-700-5998" in note or "海康威视" in note

    def test_unparseable_version(self):
        supports, note = check_firmware_support("unknown")
        assert supports is False
        assert "无法解析" in note or "Cannot parse" in note


class TestBuildProbeXml:
    def test_produces_valid_xml(self):
        probe = _build_probe_xml()
        # Should be valid XML
        root = ET.fromstring(probe.decode("utf-8"))
        assert root.tag == "Probe"
        uuid_elem = root.find("Uuid")
        assert uuid_elem is not None
        assert len(uuid_elem.text) > 0
        types_elem = root.find("Types")
        assert types_elem is not None
        assert types_elem.text == "inquiry"

    def test_produces_different_uuids(self):
        probe1 = _build_probe_xml()
        probe2 = _build_probe_xml()
        # UUIDs should be different
        assert probe1 != probe2


class TestParseSadpResponse:
    def _make_response_xml(self, **fields) -> bytes:
        """Build a mock SADP response XML."""
        parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<ProbeMatch>"]
        for key, value in fields.items():
            parts.append(f"<{key}>{value}</{key}>")
        parts.append("</ProbeMatch>")
        return "".join(parts).encode("utf-8")

    def test_parses_full_response(self):
        data = self._make_response_xml(
            DeviceSN="DS-2CD2432F-IW20150126CCCH502126167",
            DeviceDescription="DS-2CD2432F-IW",
            IPv4Address="10.1.1.251",
            SoftwareVersion="V5.2.5build 141201",
            DSPVersion="V5.0, build 140714",
            BootTime="2016-03-06 09:18:17",
            MAC="c0-56-e3-fe-42-92",
            HttpPort="80",
            CommandPort="8000",
            DHCP="false",
        )
        device = _parse_sadp_response(data, ("10.1.1.251", 37020))
        assert device is not None
        assert device.serial_number == "DS-2CD2432F-IW20150126CCCH502126167"
        assert device.device_description == "DS-2CD2432F-IW"
        assert device.ip_address == "10.1.1.251"
        assert device.software_version == "V5.2.5build 141201"
        assert device.boot_time == "2016-03-06 09:18:17"
        assert device.mac == "c0-56-e3-fe-42-92"
        assert device.supports_offline_reset is True

    def test_parses_new_firmware_device(self):
        data = self._make_response_xml(
            DeviceSN="DS-2CD3525FV3-IT20231211AACHAX8748548",
            DeviceDescription="DS-2CD3525FV3-IT",
            IPv4Address="192.168.1.100",
            SoftwareVersion="V7.3.0build 230901",
            BootTime="2024-03-15 10:00:00",
        )
        device = _parse_sadp_response(data, ("192.168.1.100", 37020))
        assert device is not None
        assert device.serial_number == "DS-2CD3525FV3-IT20231211AACHAX8748548"
        assert device.supports_offline_reset is False
        assert "不支持离线" in device.firmware_note or "NOT support" in device.firmware_note

    def test_no_device_sn_returns_none(self):
        data = self._make_response_xml(
            DeviceDescription="Unknown",
            IPv4Address="10.0.0.1",
        )
        device = _parse_sadp_response(data, ("10.0.0.1", 37020))
        assert device is None

    def test_invalid_xml_returns_none(self):
        data = b"this is not xml"
        device = _parse_sadp_response(data, ("10.0.0.1", 37020))
        assert device is None

    def test_empty_data_returns_none(self):
        data = b""
        device = _parse_sadp_response(data, ("10.0.0.1", 37020))
        assert device is None

    def test_device_to_dict(self):
        data = self._make_response_xml(
            DeviceSN="DS-TEST123",
            SoftwareVersion="V4.5.0",
            BootTime="2020-01-01 00:00:00",
            IPv4Address="192.168.1.1",
        )
        device = _parse_sadp_response(data, ("192.168.1.1", 37020))
        assert device is not None
        d = device.to_dict()
        assert d["serial_number"] == "DS-TEST123"
        assert d["ip_address"] == "192.168.1.1"
        assert d["boot_time"] == "2020-01-01 00:00:00"
        assert d["supports_offline_reset"] is True
        assert isinstance(d["firmware_note"], str)

    def test_xml_with_binary_prefix(self):
        """SADP responses may have binary header before XML."""
        xml_part = self._make_response_xml(
            DeviceSN="DS-2CD2142FWD-I20170718AAWRC22800338",
            SoftwareVersion="V5.2.0build 160412",
            BootTime="2024-03-15 08:30:00",
        )
        # Prepend some binary data
        data = b"\x00\x01\x02\x03" + xml_part
        device = _parse_sadp_response(data, ("10.0.0.5", 37020))
        assert device is not None
        assert device.serial_number == "DS-2CD2142FWD-I20170718AAWRC22800338"
        assert device.supports_offline_reset is True
