"""
海康威视密码重置服务层
Hikvision Password Reset Service Layer

负责从 QR 码内容中获取重置密钥的业务逻辑。
Handles the business logic for obtaining reset keys from QR codes.

支持的场景 / Supported scenarios:
  1. QR 码包含 URL → 请求该 URL 并解析密钥（支持多步跳转和 WAF 重试）
     QR code contains a URL → fetch it and parse the key (with redirect following & WAF retry)
  2. QR 码包含设备原始数据 → 离线算法生成密钥
     QR code contains raw device data → offline key generation
  3. 直接提供序列号 + 日期 → 离线算法生成密钥
     Direct serial number + date input → offline key generation
  4. QR 码包含 SADP 挑战数据 → 提交至海康服务端点获取密钥
     QR code contains SADP challenge data → submit to Hikvision service endpoint for key
  5. QR 码包含海康服务二维码内容 → 直接调用服务接口获取密钥
     QR code contains Hikvision service QR content → call service API for key

安全说明 / Security note:
  为防止 SSRF 攻击，URL 请求仅限于已知的海康威视及相关域名白名单。
  To prevent SSRF, URL fetching is restricted to a Hikvision/WeChat domain allowlist.
"""

import json
import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import urlparse

import httpx

from .keygen import generate_key_from_serial_date, generate_key_v1

logger = logging.getLogger(__name__)

# 已知的海康威视服务域名白名单（含微信服务域名，因微信扫码流程需要）
# Known Hikvision service domain allowlist (includes WeChat domains for scan flow)
HIKVISION_DOMAINS = [
    "hikvision.com",
    "hikconnect.com",
    "hik-connect.com",
    "lechange.com",
    "ezviz.com",
    "hikvision.com.cn",
    "hikiot.com",
]

# 微信相关域名白名单（SADP 扫码流程经由微信中转）
# WeChat-related domain allowlist (SADP scan flow routes through WeChat)
WECHAT_DOMAINS = [
    "weixin.qq.com",
    "qq.com",
]

# 模拟移动端浏览器（微信风格）的 User-Agent
# User agent to mimic a mobile browser (WeChat-like)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 12; SM-G9910) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36 "
    "MicroMessenger/8.0.40"
)

# 已知的海康威视密码重置服务端点（用于提交挑战数据获取密钥）
# Known Hikvision password reset service endpoints (for submitting challenge data)
_HIKVISION_RESET_ENDPOINTS = [
    "https://servicewechat.hikvision.com/wechat/newqrcode2/",
    "https://dmp.hikvision.com/h5wechat/sales/deptcus/index.html",
]

# WAF 检测特征字符串
# WAF detection signature strings
_WAF_SIGNATURES = [
    "changePageElem",
    "errorTip",
    "云安全平台检测到您当前的访问行为存在异常",
]

# 从响应内容中提取密钥的正则表达式列表
# Regex patterns for extracting keys from responses
KEY_PATTERNS = [
    r'"key"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"securityCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"safeCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"resetCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"verifyCode"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"code"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"password"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'"resetPassword"\s*:\s*"([A-Za-z0-9\-]{4,})"',
    r'安全码[：:]\s*([A-Za-z0-9\-]{4,})',
    r'重置口令[：:]\s*([A-Za-z0-9\-]{4,})',
    r'重置密码[：:]\s*([A-Za-z0-9\-]{4,})',
    r'验证码[：:]\s*([0-9]{4,})',
    r'密钥[：:]\s*([A-Za-z0-9\-]{4,})',
]

# 从响应 HTML/JS 中提取跳转 URL 的正则表达式
# Patterns to extract redirect/secondary URLs from HTML/JS responses
_REDIRECT_URL_PATTERNS = [
    r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
    r'window\.location\s*=\s*["\']([^"\']+)["\']',
    r'location\.replace\s*\(\s*["\']([^"\']+)["\']\s*\)',
    r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\']+)["\']',
    r'href\s*=\s*["\']([^"\']*(?:reset|qrcode|password)[^"\']*)["\']',
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
      1. URL（http/https）→ 请求并提取密钥（支持多步跳转）
         URL (http/https) → fetch and extract key (with multi-step redirect following)
      2. 设备数据字符串（如 "B:DS-XXXX..."）→ 离线算法
         Device data string (e.g. "B:DS-XXXX...") → offline algorithm
      3. SADP 挑战数据 → 提交至海康服务端点
         SADP challenge data → submit to Hikvision service endpoints
      4. 其他内容 → 尝试提交至海康服务端点，失败则返回原始内容
         Other content → try Hikvision service endpoints, or return raw content

    Args:
        qr_content: QR 码解码后的字符串 / The decoded string from the QR code

    Returns:
        包含密钥或错误信息的 ResetKeyResult
        ResetKeyResult with the key or error information
    """
    qr_content = qr_content.strip()
    # Log only content type/length to avoid leaking sensitive tokens in URL query params
    if qr_content.startswith(("http://", "https://")):
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

    # 检查是否为 SADP 挑战格式 / Check if it's SADP challenge format
    if _looks_like_sadp_challenge(qr_content):
        return await _process_sadp_challenge(qr_content)

    # 尝试提交至海康服务端点 / Try submitting to Hikvision service endpoints
    service_result = await _try_hikvision_service_endpoints(qr_content)
    if service_result and service_result.key:
        return service_result

    # 无法自动处理，返回原始内容 / Cannot process automatically, return raw content
    return ResetKeyResult(
        qr_content=qr_content,
        method="raw",
        error=(
            "QR code decoded successfully but could not automatically extract key. "
            "The content has been analyzed but does not match any known format. "
            "You can try: (1) Submit this QR content to Hikvision support via the "
            "'海康威视客户服务' WeChat public account → 服务支持 → 密码重置, "
            "(2) Use the serial number and date for offline key generation (older firmware only), "
            "or (3) Contact Hikvision support at 400-700-5998."
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

    支持多步跳转：先请求初始 URL，如发现 JavaScript 跳转或二次 URL，继续追踪。
    Supports multi-step: fetch initial URL, follow JS redirects or secondary URLs.

    安全措施：仅允许请求白名单内的域名，防止 SSRF 攻击。
    Security: Only URLs belonging to allowed domains are fetched to prevent SSRF.
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
    if not _is_allowed_domain(hostname):
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=(
                f"URL hostname '{hostname}' is not an allowed domain. "
                f"Allowed domains: {', '.join(HIKVISION_DOMAINS + WECHAT_DOMAINS)}. "
                "Only Hikvision/WeChat service URLs from QR codes are supported."
            ),
        )

    try:
        content, final_url = await _fetch_with_waf_retry(url)

        # 从响应中提取密钥 / Try to extract key from response
        key = _extract_key_from_response(content)
        if key:
            return ResetKeyResult(
                key=key,
                qr_content=url,
                method="url_fetch",
                raw_response=content[:2000],
            )

        # 尝试从响应中提取二次跳转 URL / Try to extract secondary redirect URLs
        redirect_urls = _find_redirect_urls(content)
        for redirect_url in redirect_urls:
            redirect_parsed = urlparse(redirect_url)
            redirect_host = redirect_parsed.hostname or ""
            if not _is_allowed_domain(redirect_host):
                continue
            try:
                redirect_content, _ = await _fetch_with_waf_retry(redirect_url)
                redirect_key = _extract_key_from_response(redirect_content)
                if redirect_key:
                    return ResetKeyResult(
                        key=redirect_key,
                        qr_content=url,
                        method="url_redirect",
                        raw_response=redirect_content[:2000],
                    )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.debug("Failed to follow redirect URL %s: %s", redirect_url, exc)

        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=(
                "Fetched URL successfully but could not extract reset key from response. "
                "The page may require WeChat authentication. "
                "Try submitting the QR content via '海康威视客户服务' WeChat public account "
                "→ 服务支持 → 密码重置."
            ),
            raw_response=content[:2000],
        )

    except httpx.HTTPStatusError as exc:
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=f"HTTP error {exc.response.status_code} when fetching URL.",
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
    # 首先尝试解析 JSON 响应 / First try parsing as JSON
    json_key = _extract_key_from_json(content)
    if json_key:
        return json_key

    for pattern in KEY_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            key = match.group(1)
            if len(key) >= 4:
                return key
    return None


def _extract_key_from_json(content: str) -> Optional[str]:
    """
    尝试从 JSON 响应中提取密钥。
    Try to extract a reset key from a JSON response body.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    # 检查常见的密钥字段名 / Check common key field names
    key_fields = [
        "key", "securityCode", "safeCode", "resetCode",
        "verifyCode", "password", "resetPassword", "code",
        "安全码", "重置口令", "密钥",
    ]
    for field in key_fields:
        value = data.get(field)
        if isinstance(value, str) and len(value) >= 4:
            return value

    # 检查嵌套数据字段 / Check nested data fields
    nested = data.get("data")
    if isinstance(nested, dict):
        for field in key_fields:
            value = nested.get(field)
            if isinstance(value, str) and len(value) >= 4:
                return value

    return None


def _is_allowed_domain(hostname: str) -> bool:
    """
    检查域名是否在允许列表中。
    Check if the hostname is in the allowed domain list.

    使用严格的域名后缀匹配，防止绕过。
    Uses strict domain suffix matching to prevent bypass.
    """
    all_domains = HIKVISION_DOMAINS + WECHAT_DOMAINS
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in all_domains
    )


def _looks_like_sadp_challenge(content: str) -> bool:
    """
    判断内容是否为 SADP 挑战数据格式。
    Check if the content looks like SADP challenge data.

    常见格式 / Common formats:
      - "SN:DS-XXXX;DATE:YYYY-MM-DD;CHALLENGE:XXXX"
      - 包含设备序列号和挑战码的分号分隔字符串
        Semicolon-separated string with device SN and challenge
      - QRC 格式（"QRC0301..." 前缀 + base64 数据）
        QRC format ("QRC0301..." prefix + base64 data)
    """
    # QRC 格式 / QRC format
    if re.match(r'^QRC\d{4,}', content):
        return True
    # SN + CHALLENGE 格式 / SN + CHALLENGE format
    if re.search(r'SN[:\s]*DS-', content, re.IGNORECASE) and re.search(r'CHALLENGE', content, re.IGNORECASE):
        return True
    return False


async def _process_sadp_challenge(content: str) -> ResetKeyResult:
    """
    处理 SADP 挑战数据格式。
    Process SADP challenge data format.

    挑战数据包含加密的设备信息，需提交至海康服务端点获取密钥。
    Challenge data contains encrypted device info; needs to be submitted
    to Hikvision service endpoints for key retrieval.
    """
    # 提取设备序列号（如果有） / Extract device serial (if present)
    serial_match = re.search(r'(DS-[A-Z0-9\-]+)', content, re.IGNORECASE)
    serial = serial_match.group(1) if serial_match else None

    # 尝试提交至海康服务端点 / Try submitting to Hikvision service endpoints
    service_result = await _try_hikvision_service_endpoints(content)
    if service_result and service_result.key:
        return service_result

    # 如果有序列号，尝试离线生成 / If serial found, try offline generation
    if serial:
        today = date.today()
        key = generate_key_v1(serial, today)
        return ResetKeyResult(
            key=key,
            qr_content=content,
            method="offline_v1",
            error=(
                f"Could not reach Hikvision service. Generated offline key for "
                f"serial {serial} with date {today}. Note: This works for older "
                "firmware only (< 5.3.0). For newer firmware, submit the QR content "
                "via '海康威视客户服务' WeChat → 服务支持 → 密码重置."
            ),
        )

    return ResetKeyResult(
        qr_content=content,
        method="sadp_challenge",
        error=(
            "SADP challenge data detected but could not retrieve reset key from "
            "Hikvision service. The challenge data requires server-side processing. "
            "Please submit this data via '海康威视客户服务' WeChat public account "
            "→ 服务支持 → 密码重置, or contact Hikvision support at 400-700-5998."
        ),
    )


async def _try_hikvision_service_endpoints(qr_content: str) -> Optional[ResetKeyResult]:
    """
    尝试将 QR 内容提交至已知的海康威视服务端点。
    Try submitting QR content to known Hikvision service endpoints.

    模拟微信扫码流程，向服务端点 POST 数据。
    Simulates the WeChat scan flow by POSTing data to service endpoints.
    """
    for endpoint in _HIKVISION_RESET_ENDPOINTS:
        try:
            logger.info("Trying Hikvision service endpoint: %s", endpoint)
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": MOBILE_UA,
                    "Content-Type": "application/json",
                    "Referer": endpoint,
                    "Origin": f"{urlparse(endpoint).scheme}://{urlparse(endpoint).hostname}",
                },
                follow_redirects=True,
            ) as client:
                # 先尝试 POST JSON / Try POST with JSON
                try:
                    response = await client.post(
                        endpoint,
                        json={"qrContent": qr_content, "qrData": qr_content},
                    )
                    if response.status_code < 400:
                        key = _extract_key_from_response(response.text)
                        if key:
                            return ResetKeyResult(
                                key=key,
                                qr_content=qr_content,
                                method="hikvision_service",
                                raw_response=response.text[:2000],
                            )
                except httpx.RequestError as exc:
                    logger.debug("POST to %s failed: %s", endpoint, exc)

                # 再尝试 GET（将 QR 内容作为参数）/ Try GET with QR content as param
                try:
                    response = await client.get(
                        endpoint,
                        params={"code": qr_content},
                    )
                    if response.status_code < 400:
                        key = _extract_key_from_response(response.text)
                        if key:
                            return ResetKeyResult(
                                key=key,
                                qr_content=qr_content,
                                method="hikvision_service",
                                raw_response=response.text[:2000],
                            )
                except httpx.RequestError as exc:
                    logger.debug("GET to %s failed: %s", endpoint, exc)

        except Exception as exc:
            logger.debug("Service endpoint %s failed: %s", endpoint, exc)

    return None


async def _fetch_with_waf_retry(url: str, max_retries: int = 2) -> tuple[str, str]:
    """
    请求 URL，带 WAF 检测和 Cookie 重试机制。
    Fetch a URL with WAF detection and cookie-based retry.

    海康云安全 WAF 会在首次访问时设置 Cookie，第二次请求带上 Cookie 后即可通过。
    Hikvision cloud WAF sets cookies on first visit; subsequent requests with
    those cookies are allowed through.

    Args:
        url: 要请求的 URL / URL to fetch
        max_retries: 最大重试次数 / Maximum retry attempts

    Returns:
        (响应内容, 最终 URL) / (response content, final URL)
    """
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": MOBILE_UA},
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.text
        final_url = str(response.url)

        # 检查是否被 WAF 拦截 / Check for WAF interception
        for retry in range(max_retries):
            if not _is_waf_response(content):
                break
            logger.info("WAF detected, retrying with cookies (attempt %d)", retry + 1)
            # 重试时自动携带上次请求设置的 Cookie / Retry with cookies from previous request
            response = await client.get(
                url,
                headers={"Referer": final_url},
            )
            response.raise_for_status()
            content = response.text
            final_url = str(response.url)

        return content, final_url


def _is_waf_response(content: str) -> bool:
    """
    检测响应是否为 WAF 拦截页面。
    Detect if the response is a WAF interception page.
    """
    return any(sig in content for sig in _WAF_SIGNATURES)


def _find_redirect_urls(content: str) -> list[str]:
    """
    从 HTML/JS 响应中提取跳转 URL。
    Extract redirect URLs from HTML/JS response content.

    海康服务页面经常使用 JavaScript 跳转而非标准 HTTP 重定向。
    Hikvision service pages often use JavaScript redirects instead of HTTP redirects.
    """
    urls = []
    for pattern in _REDIRECT_URL_PATTERNS:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            candidate = match.group(1)
            if candidate.startswith(("http://", "https://")):
                urls.append(candidate)
    # 去重并保持顺序 / Deduplicate while preserving order
    seen: set[str] = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
    return unique_urls


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
