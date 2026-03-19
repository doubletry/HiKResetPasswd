"""
海康威视密码重置密钥生成器
Hikvision Password Reset Key Generator

使用海康威视专有的安全码生成算法（非 MD5），基于设备序列号和设备内部日期。
Uses Hikvision's proprietary security code generation algorithm (not MD5),
based on the device serial number and the device's internal date.

算法步骤 / Algorithm steps:
  1. 将序列号和日期（YYYYMMDD）拼接成种子字符串
     Concatenate serial number and date (YYYYMMDD) to form a seed string
  2. 对每个字符计算加权校验和：sum((charCode * (i+1)) ^ (i+1))
     Calculate a weighted checksum for each character: sum((charCode * (i+1)) ^ (i+1))
  3. 乘以魔数常量 1751873395，截断为 32 位无符号整数
     Multiply by magic constant 1751873395, truncate to 32-bit unsigned integer
  4. 将结果的每位数字通过固定映射表替换为字母/数字
     Map each digit of the result through a fixed substitution table:
       0→Q  1→R  2→S  3→q  4→r  5→d  6→e  7→y  8→z  9→9

参考实现 / Reference implementations:
  - https://github.com/mecko/hikvision-password-reset
  - https://github.com/cameronnewman/hikvision-tooling
  - https://ipcamtalk.com/pages/hikvision-password-reset-tool/
"""

import ctypes
from datetime import date, datetime

# 魔数常量（用于步骤 3 的乘法）/ Magic multiplier constant (step 3)
_MAGIC_MULTIPLIER = 1751873395

# 数字→字符映射表 / Digit-to-character substitution table (step 4)
_DIGIT_MAP = {
    "0": "Q",
    "1": "R",
    "2": "S",
    "3": "q",
    "4": "r",
    "5": "d",
    "6": "e",
    "7": "y",
    "8": "z",
    "9": "9",
}


def generate_key_v1(serial: str, reset_date: date) -> str:
    """
    为海康威视设备生成密码重置安全码。
    Generate a password reset security code for Hikvision devices.

    适用于旧固件（< 5.3.0）的设备。新固件设备需通过 SADP 导出设备特征文件
    并联系海康技术支持获取解锁文件。
    Works for devices with older firmware (< 5.3.0). Newer firmware devices require
    exporting a device characteristic file via SADP and contacting Hikvision support.

    Args:
        serial: 设备序列号（区分大小写，需与 SADP 中完全一致）
                Device serial number (case-sensitive, must match SADP exactly)
        reset_date: SADP 中显示的设备当前日期（Start Time 列中的日期）
                    The device's internal date (from the Start Time column in SADP)

    Returns:
        密码重置安全码（可变长度字符串）
        Password reset security code (variable-length string)
    """
    date_str = reset_date.strftime("%Y%m%d")
    return _generate_security_code(serial, date_str)


def generate_key_from_serial_date(serial: str, date_str: str) -> str:
    """
    根据序列号和日期字符串生成重置安全码。
    Generate a reset security code from serial number and date string.

    Args:
        serial: 设备序列号 / Device serial number
        date_str: 日期字符串，支持 YYYYMMDD 或 YYYY-MM-DD 格式
                  Date string in YYYYMMDD or YYYY-MM-DD format

    Returns:
        密码重置安全码 / Password reset security code

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


def _generate_security_code(serial: str, date_str: str) -> str:
    """
    海康威视专有安全码生成算法的核心实现。
    Core implementation of the Hikvision proprietary security code algorithm.

    Args:
        serial: 设备序列号 / Device serial number
        date_str: 日期字符串（YYYYMMDD 格式）/ Date string (YYYYMMDD format)

    Returns:
        安全码字符串 / Security code string
    """
    seed = serial + date_str

    # 步骤 1-2：计算加权校验和 / Steps 1-2: Calculate weighted checksum
    # sum((charCode * position) XOR position) for each character
    magic: int = 0
    for i, ch in enumerate(seed):
        pos = i + 1
        magic += (ord(ch) * pos) ^ pos

    # 步骤 3：乘以魔数常量并截断为 32 位无符号整数
    # Step 3: Multiply by magic constant and truncate to unsigned 32-bit
    magic *= _MAGIC_MULTIPLIER
    magic = ctypes.c_uint32(magic).value

    # 步骤 4：将十进制表示的每位数字通过映射表替换
    # Step 4: Map each digit of the decimal representation
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in str(magic))
