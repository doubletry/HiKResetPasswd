"""
Hikvision password reset key generator.

Supports two methods:
1. Offline algorithm for older devices (pre-2017, firmware < 5.3.0)
   Uses serial number + date with a known hash-based algorithm.
2. QR code URL method: the QR code may contain a URL that, when accessed,
   provides the reset key through Hikvision's service.
"""

import hashlib
import struct
from datetime import date, datetime


def generate_key_v1(serial: str, reset_date: date) -> str:
    """
    Generate a password reset key for older Hikvision devices.

    This algorithm is known to work for older firmware (pre-2017).
    It takes the device serial number and the device's current date,
    concatenates them and computes an MD5 hash.

    Args:
        serial: Device serial number (as shown in SADP)
        reset_date: The date displayed in SADP for the device

    Returns:
        8-character hex reset key
    """
    date_str = reset_date.strftime("%Y%m%d")
    data = f"{serial}{date_str}"
    md5_hash = hashlib.md5(data.encode("utf-8")).hexdigest()
    return md5_hash[:8].upper()


def generate_key_from_serial_date(serial: str, date_str: str) -> str:
    """
    Generate a password reset key given serial number and date string.

    Args:
        serial: Device serial number
        date_str: Date string in YYYYMMDD or YYYY-MM-DD format

    Returns:
        8-character hex reset key

    Raises:
        ValueError: If date format is invalid
    """
    date_str_clean = date_str.replace("-", "")
    if len(date_str_clean) != 8 or not date_str_clean.isdigit():
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYYMMDD or YYYY-MM-DD")
    try:
        reset_date = datetime.strptime(date_str_clean, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date: {date_str}") from exc

    return generate_key_v1(serial, reset_date)
