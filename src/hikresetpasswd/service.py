"""
海康威视密码重置服务层
Hikvision Password Reset Service Layer

负责从 QR 码内容中获取重置密钥的业务逻辑。
Handles the business logic for obtaining reset keys from QR codes.

支持的场景 / Supported scenarios:
  1. QR 码包含 URL → 请求该 URL 并解析密钥
     QR code contains a URL → fetch it and parse the key
  2. QR 码包含设备原始数据 → 离线算法生成密钥
     QR code contains raw device data → offline key generation
  3. 直接提供序列号 + 日期 → 离线算法生成密钥
     Direct serial number + date input → offline key generation

安全说明 / Security note:
  为防止 SSRF 攻击，URL 请求仅限于已知的海康威视域名白名单。
  To prevent SSRF, URL fetching is restricted to a Hikvision domain allowlist.
"""

import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import urlparse

import httpx

from .keygen import generate_key_from_serial_date, generate_key_v1

logger = logging.getLogger(__name__)

# 已知的海康威视服务域名白名单
# Known Hikvision service domain allowlist
HIKVISION_DOMAINS = [
    "hikvision.com",
    "hikconnect.com",
    "hik-connect.com",
    "lechange.com",
    "ezviz.com",
]

# 模拟移动端浏览器（微信风格）的 User-Agent
# User agent to mimic a mobile browser (WeChat-like)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 12; SM-G9910) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36 "
    "MicroMessenger/8.0.40"
)

# 从响应内容中提取密钥的正则表达式列表
# Regex patterns for extracting keys from responses
KEY_PATTERNS = [
    r'"key"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"securityCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"safeCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"resetCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"verifyCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"code"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'安全码[：:]\s*([A-Za-z0-9\-]{4,})',
    r'重置口令[：:]\s*([A-Za-z0-9\-]{4,})',
    r'验证码[：:]\s*([0-9]{4,})',
]


class ResetKeyResult:
    """密钥请求的结果对象 / Result from a reset key request."""

    def __init__(
        self,
        key: Optional[str] = None,
        qr_content: Optional[str] = None,
        method: Optional[str] = None,
        error: Optional[str] = None,
        raw_response: Optional[str] = None,
    ):
        self.key = key
        self.qr_content = qr_content
        self.method = method
        self.error = error
        self.raw_response = raw_response

    def to_dict(self) -> dict:
        """转为字典，供 Pydantic 模型使用 / Convert to dict for Pydantic model."""
        return {
            "key": self.key,
            "qr_content": self.qr_content,
            "method": self.method,
            "error": self.error,
            "raw_response": self.raw_response,
        }


async def process_qr_content(qr_content: str) -> ResetKeyResult:
    """
    处理已解码的 QR 内容并尝试获取重置密钥。
    Process the decoded QR code content and attempt to obtain a reset key.

    QR 内容的几种可能形式 / QR content can be:
      1. URL（http/https）→ 请求并提取密钥
         URL (http/https) → fetch and extract key
      2. 设备数据字符串（如 "B:DS-XXXX..."）→ 离线算法
         Device data string (e.g. "B:DS-XXXX...") → offline algorithm
      3. 其他内容 → 返回原始内容供用户手动处理
         Other content → return raw content for manual processing

    Args:
        qr_content: QR 码解码后的字符串 / The decoded string from the QR code

    Returns:
        包含密钥或错误信息的 ResetKeyResult
        ResetKeyResult with the key or error information
    """
    qr_content = qr_content.strip()
    # Log only content type/length to avoid leaking sensitive tokens in URL query params
    if qr_content.startswith(("http://", "https://")):
        from urllib.parse import urlparse

        parsed = urlparse(qr_content)
        logger.info("Processing QR content: URL (%s://%s, %d chars)", parsed.scheme, parsed.hostname, len(qr_content))
    else:
        logger.info("Processing QR content: text (%d chars)", len(qr_content))

    # 检查是否为 URL / Check if it's a URL
    if qr_content.startswith(("http://", "https://")):
        return await _process_url(qr_content)

    # 检查是否为海康设备数据格式（如 "B:DS-7908HQH-SH..."）
    # Check if it's Hikvision device data format (e.g. "B:DS-7908HQH-SH...")
    if _looks_like_device_data(qr_content):
        return _process_device_data(qr_content)

    # 无法自动处理，返回原始内容 / Cannot process automatically, return raw content
    return ResetKeyResult(
        qr_content=qr_content,
        method="raw",
        error=(
            "QR code decoded successfully but could not automatically extract key. "
            "Please use the QR content to submit to Hikvision support manually, "
            "or provide the serial number and date for offline key generation."
        ),
    )


def _looks_like_device_data(content: str) -> bool:
    """
    判断内容是否符合海康设备数据格式。
    Check if the content looks like Hikvision device data.
    """
    # 格式一：单字母前缀 + 冒号，例如 "B:DS-..." / Format: single letter + colon, e.g. "B:DS-..."
    if re.match(r'^[A-Z]:', content):
        return True
    # 格式二：直接以设备型号开头 / Format: starts with device model prefix
    if re.match(r'^DS-', content, re.IGNORECASE):
        return True
    return False


def _process_device_data(content: str) -> ResetKeyResult:
    """
    处理设备数据格式的 QR 内容，尝试提取序列号并生成密钥。
    Process device data format QR code content.
    Tries to extract serial number and use the offline key generator.
    """
    # 从内容中提取序列号（格式："B:DS-7908HQH-SH..."）
    # Extract serial number (format: "B:DS-7908HQH-SH...")
    serial_match = re.search(r'(DS-[A-Z0-9\-]+)', content, re.IGNORECASE)

    if serial_match:
        serial = serial_match.group(1)
        # 使用今天的日期（用户可在离线生成选项卡中调整）
        # Use today's date (user can adjust in the offline generation tab)
        today = date.today()
        key = generate_key_v1(serial, today)
        return ResetKeyResult(
            key=key,
            qr_content=content,
            method="offline_v1",
            error=(
                f"Generated key using offline algorithm for serial {serial} "
                f"with date {today}. Note: This works for older firmware only. "
                "If this doesn't work, please provide the exact device date shown in SADP."
            ),
        )

    return ResetKeyResult(
        qr_content=content,
        method="raw",
        error=(
            "Device data format detected but could not extract serial number. "
            "Please provide the serial number and date for offline key generation."
        ),
    )


async def _process_url(url: str) -> ResetKeyResult:
    """
    请求 QR 码中的 URL 并尝试提取重置密钥。
    Fetch a URL from the QR code and attempt to extract the reset key.

    安全措施：仅允许请求白名单内的海康威视域名，防止 SSRF 攻击。
    Security: Only URLs belonging to known Hikvision domains are fetched to prevent SSRF.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # 仅允许 http/https 协议 / Only allow http/https scheme
    if parsed.scheme not in ("http", "https"):
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=f"URL scheme '{parsed.scheme}' is not allowed. Only http/https is supported.",
        )

    # 严格域名后缀匹配，防止 "evil.hikvision.com.attacker.com" 绕过
    # Strict domain suffix match to prevent "evil.hikvision.com.attacker.com" bypass
    is_hikvision = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in HIKVISION_DOMAINS
    )

    if not is_hikvision:
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=(
                f"URL hostname '{hostname}' is not a known Hikvision domain. "
                f"Allowed domains: {', '.join(HIKVISION_DOMAINS)}. "
                "Only Hikvision service URLs from QR codes are supported."
            ),
        )

    try:
        # 模拟移动端微信浏览器请求 / Simulate mobile WeChat browser request
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": MOBILE_UA},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text

        # 从响应中提取密钥 / Try to extract key from response
        key = _extract_key_from_response(content)
        if key:
            return ResetKeyResult(
                key=key,
                qr_content=url,
                method="url_fetch",
                raw_response=content[:2000],
            )

        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error="Fetched URL successfully but could not extract reset key from response.",
            raw_response=content[:2000],
        )

    except httpx.HTTPStatusError as exc:
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=f"HTTP error {exc.response.status_code} when fetching URL: {url}",
        )
    except httpx.RequestError as exc:
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=f"Network error when fetching URL: {exc}",
        )


def _extract_key_from_response(content: str) -> Optional[str]:
    """
    从 HTML/JSON 响应内容中尝试提取重置密钥。
    Try to extract a reset key from HTML/JSON response content.
    """
    for pattern in KEY_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            key = match.group(1)
            if len(key) >= 4:
                return key
    return None


async def generate_key_offline(serial: str, date_str: str) -> ResetKeyResult:
    """
    使用离线算法生成重置密钥。
    Generate a reset key using the offline algorithm.

    适用于旧型号海康设备（固件 < 5.3.0，2017 年以前）。
    Works for older Hikvision devices (firmware < 5.3.0, pre-2017).

    Args:
        serial: SADP 中显示的设备序列号 / Device serial number from SADP
        date_str: SADP 中显示的设备日期（YYYYMMDD 或 YYYY-MM-DD 格式）
                  Device date from SADP in YYYYMMDD or YYYY-MM-DD format

    Returns:
        包含生成密钥的 ResetKeyResult / ResetKeyResult with the generated key
    """
    try:
        key = generate_key_from_serial_date(serial, date_str)
        return ResetKeyResult(
            key=key,
            method="offline_v1",
            qr_content=f"Serial: {serial}, Date: {date_str}",
        )
    except ValueError as exc:
        return ResetKeyResult(
            error=str(exc),
            method="offline_v1",
        )
