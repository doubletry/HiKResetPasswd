"""Tests for the key generator module."""

import pytest
from datetime import date

from backend.keygen import generate_key_v1, generate_key_from_serial_date


class TestGenerateKeyV1:
    def test_generates_8_char_hex_string(self):
        """Key should be 8 uppercase hex characters."""
        key = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 15))
        assert len(key) == 8
        assert all(c in "0123456789ABCDEF" for c in key)

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

    def test_key_is_uppercase(self):
        """Key should be uppercase."""
        key = generate_key_v1("DS-2CD2T45G0P-I", date(2024, 3, 15))
        assert key == key.upper()


class TestGenerateKeyFromSerialDate:
    def test_yyyymmdd_format(self):
        """Should accept YYYYMMDD format."""
        key = generate_key_from_serial_date("DS-2CD2T45G0P-I", "20240315")
        assert len(key) == 8

    def test_yyyy_mm_dd_format(self):
        """Should accept YYYY-MM-DD format."""
        key = generate_key_from_serial_date("DS-2CD2T45G0P-I", "2024-03-15")
        assert len(key) == 8

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
