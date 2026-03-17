"""
Hikvision password reset service.

Handles the business logic for obtaining reset keys from QR codes.
Supports:
1. QR codes that contain URLs - fetches the URL and parses the key
2. QR codes with raw device data - uses offline key generation
3. Direct serial number + date input for older devices
"""

import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

from .keygen import generate_key_from_serial_date, generate_key_v1

logger = logging.getLogger(__name__)

# Known Hikvision service domains
HIKVISION_DOMAINS = [
    "hikvision.com",
    "hikconnect.com",
    "hik-connect.com",
    "lechange.com",
    "ezviz.com",
]

# User agent to mimic a mobile browser (WeChat-like)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 12; SM-G9910) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36 "
    "MicroMessenger/8.0.40"
)

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
    """Result from a reset key request."""

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
        return {
            "key": self.key,
            "qr_content": self.qr_content,
            "method": self.method,
            "error": self.error,
            "raw_response": self.raw_response,
        }


async def process_qr_content(qr_content: str) -> ResetKeyResult:
    """
    Process the decoded QR code content and attempt to obtain a reset key.

    The QR code content can be:
    1. A URL (HTTP/HTTPS) → fetch it and extract the key
    2. A data string like "B:DS-XXXX..." → extract device info and use offline algorithm
    3. A plain serial number → use with current date for offline algorithm

    Args:
        qr_content: The decoded string from the QR code

    Returns:
        ResetKeyResult with the key or error information
    """
    qr_content = qr_content.strip()
    logger.info("Processing QR content: %s...", qr_content[:50])

    # Check if it's a URL
    if qr_content.startswith(("http://", "https://")):
        return await _process_url(qr_content)

    # Check if it's Hikvision device data format (e.g., "B:DS-7908HQH-SH...")
    if _looks_like_device_data(qr_content):
        return _process_device_data(qr_content)

    # Return the raw content for the user to process manually
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
    """Check if the content looks like Hikvision device data."""
    # Format: "B:DS-XXXX..." or starts with device model pattern
    if re.match(r'^[A-Z]:', content):
        return True
    if re.match(r'^DS-', content, re.IGNORECASE):
        return True
    return False


def _process_device_data(content: str) -> ResetKeyResult:
    """
    Process device data format QR code content.

    Tries to extract serial number and use the offline key generator.
    """
    # Try to extract serial number from format like "B:DS-7908HQH-SH..."
    # The format is typically: PREFIX:SERIAL_NUMBER BASE64_ENCODED_DATA
    serial_match = re.search(r'(DS-[A-Z0-9\-]+)', content, re.IGNORECASE)

    if serial_match:
        serial = serial_match.group(1)
        # Use today's date as the device date (user may need to adjust)
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
    Fetch a URL from the QR code and attempt to extract the reset key.

    This handles cases where the QR code contains a URL to Hikvision's service.
    Only URLs belonging to known Hikvision domains are fetched to prevent SSRF.
    """
    # Validate that it's a Hikvision-related URL for security (prevent SSRF)
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Only allow HTTPS to known Hikvision domains
    if parsed.scheme not in ("http", "https"):
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=f"URL scheme '{parsed.scheme}' is not allowed. Only http/https is supported.",
        )

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
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": MOBILE_UA},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text

        # Try to extract key from response
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
    """Try to extract a reset key from HTML/JSON response content."""
    for pattern in KEY_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            key = match.group(1)
            if len(key) >= 4:
                return key
    return None


async def generate_key_offline(serial: str, date_str: str) -> ResetKeyResult:
    """
    Generate a reset key using the offline algorithm.

    Works for older Hikvision devices (firmware < 5.3.0, pre-2017).

    Args:
        serial: Device serial number from SADP
        date_str: Device date from SADP in YYYYMMDD or YYYY-MM-DD format

    Returns:
        ResetKeyResult with the generated key
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
