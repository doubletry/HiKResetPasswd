"""
海康威视密码重置密钥生成器
Hikvision Password Reset Key Generator

支持两种方式 / Supports two methods:
  1. 旧设备离线算法（2017年前，固件 < 5.3.0）
     Offline algorithm for older devices (pre-2017, firmware < 5.3.0)
     使用序列号 + 日期进行 MD5 哈希 / Uses serial number + date with MD5 hash.
  2. QR 码 URL 方式：QR 码包含可访问的服务器地址
     QR code URL method: QR code contains a URL to Hikvision's service.
"""

import hashlib
from datetime import date, datetime


def generate_key_v1(serial: str, reset_date: date) -> str:
    """
    为旧型号海康威视设备生成密码重置密钥。
    Generate a password reset key for older Hikvision devices.

    此算法适用于旧版固件（2017 年以前）。
    This algorithm is known to work for older firmware (pre-2017).

    算法：MD5(序列号 + 日期字符串) 取前 8 位十六进制大写
    Algorithm: MD5(serial + date_string) → first 8 hex chars (uppercase)

    Args:
        serial: 设备序列号（SADP 中显示的值）
                Device serial number (as shown in SADP)
        reset_date: SADP 中显示的设备当前日期
                    The date displayed in SADP for the device

    Returns:
        8 位大写十六进制重置密钥 / 8-character uppercase hex reset key
    """
    # 将日期格式化为 YYYYMMDD 字符串 / Format date as YYYYMMDD string
    date_str = reset_date.strftime("%Y%m%d")
    data = f"{serial}{date_str}"
    md5_hash = hashlib.md5(data.encode("utf-8")).hexdigest()
    # 取哈希前 8 位并转为大写 / Take first 8 chars and convert to uppercase
    return md5_hash[:8].upper()


def generate_key_from_serial_date(serial: str, date_str: str) -> str:
    """
    根据序列号和日期字符串生成重置密钥。
    Generate a password reset key given serial number and date string.

    Args:
        serial: 设备序列号 / Device serial number
        date_str: 日期字符串，支持 YYYYMMDD 或 YYYY-MM-DD 格式
                  Date string in YYYYMMDD or YYYY-MM-DD format

    Returns:
        8 位大写十六进制重置密钥 / 8-character uppercase hex reset key

    Raises:
        ValueError: 日期格式无效时抛出 / Raised if date format is invalid
    """
    # 去除分隔符，统一为 YYYYMMDD / Strip separators to get YYYYMMDD
    date_str_clean = date_str.replace("-", "")
    if len(date_str_clean) != 8 or not date_str_clean.isdigit():
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYYMMDD or YYYY-MM-DD")
    try:
        reset_date = datetime.strptime(date_str_clean, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date: {date_str}") from exc

    return generate_key_v1(serial, reset_date)
