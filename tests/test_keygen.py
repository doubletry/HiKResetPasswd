"""Tests for the key generator module."""

from datetime import date

import pytest

from hikresetpasswd.keygen import generate_key_from_serial_date, generate_key_v1

# 安全码中可能出现的字符集（0-9 数字映射后的结果）
# Character set that can appear in security codes (mapped from digits 0-9)
VALID_CODE_CHARS = set("QRSqrdey9z")


class TestGenerateKeyV1:
    def test_generates_code_with_valid_chars(self):
        """Code should only contain characters from the substitution table."""
        key = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 15))
        assert all(c in VALID_CODE_CHARS for c in key)

    def test_same_inputs_produce_same_key(self):
        """Same serial + date should always produce the same key."""
        key1 = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 15))
        key2 = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 15))
        assert key1 == key2

    def test_different_dates_produce_different_keys(self):
        """Different dates should produce different keys."""
        key1 = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 15))
        key2 = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 16))
        assert key1 != key2

    def test_different_serials_produce_different_keys(self):
        """Different serials should produce different keys."""
        key1 = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 15))
        key2 = generate_key_v1("DS-7908HQH-SH", date(2024, 3, 15))
        assert key1 != key2

    def test_known_value_matches_reference(self):
        """
        Cross-validate against the reference JS implementation
        (github.com/mecko/hikvision-password-reset).
        """
        key = generate_key_from_serial_date(
            "DS-2CD2142FWD-I20170718AAWRC22800338", "20240315"
        )
        assert key == "RSSQeRqeee"


class TestGenerateKeyFromSerialDate:
    def test_yyyymmdd_format(self):
        """Should accept YYYYMMDD format."""
        key = generate_key_from_serial_date("DS-2CD2T45G0P-I", "20240315")
        assert all(c in VALID_CODE_CHARS for c in key)

    def test_yyyy_mm_dd_format(self):
        """Should accept YYYY-MM-DD format."""
        key = generate_key_from_serial_date("DS-2CD2T45G0P-I", "2024-03-15")
        assert all(c in VALID_CODE_CHARS for c in key)

    def test_both_formats_same_result(self):
        """Both date formats should produce the same key."""
        key1 = generate_key_from_serial_date("DS-2CD2T45G0P-I", "20240315")
        key2 = generate_key_from_serial_date("DS-2CD2T45G0P-I", "2024-03-15")
        assert key1 == key2

    def test_invalid_date_raises_value_error(self):
        """Invalid date format should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid date"):
            generate_key_from_serial_date("DS-2CD2T45G0P-I", "not-a-date")

    def test_invalid_date_format_raises_error(self):
        """Short date string should raise ValueError."""
        with pytest.raises(ValueError):
            generate_key_from_serial_date("DS-2CD2T45G0P-I", "2024-03")

    def test_consistent_with_v1(self):
        """Should produce same key as generate_key_v1."""
        from datetime import date as d
        key_direct = generate_key_v1("DS-2CD2T45G0P-I", d(2024, 3, 15))
        key_from_str = generate_key_from_serial_date("DS-2CD2T45G0P-I", "20240315")
        assert key_direct == key_from_str
