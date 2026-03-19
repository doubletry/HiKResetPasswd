"""
海康威视密码重置服务层
Hikvision Password Reset Service Layer

负责从 QR 码内容中获取重置密钥的业务逻辑。
Handles the business logic for obtaining reset keys from QR codes.

支持的场景 / Supported scenarios:
  1. QR 码包含 URL → 请求该 URL 并解析密钥
     QR code contains a URL → fetch it and parse the key
  2. QR 码包含设备原始数据 → 离线算法生成密钥
     QR code contains raw device data → offline algorithm
  3. 直接提供序列号 + 日期 → 离线算法生成密钥
     Direct serial number + date input → offline key generation
  4. SADP 设备特征文件（二进制格式）→ 从中提取序列号后离线生成密钥
     SADP device characteristic file (binary) → extract serial, generate key offline
  5. URL 包含序列号参数（如 SADP 导出的重置链接）→ 从 URL 参数提取序列号后离线生成
     URL contains serial parameters (e.g. SADP reset link) → extract serial from URL params

安全说明 / Security note:
  为防止 SSRF 攻击，URL 请求仅限于已知的海康威视域名白名单（含微信域名，
  用于跟踪海康威视在国内通过微信公众号分发密钥的重定向链路）。
  To prevent SSRF, URL fetching is restricted to a Hikvision/WeChat domain allowlist.
  WeChat domains are included because Hikvision's reset process in China redirects through WeChat.
"""

import base64
import json
import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

from .keygen import generate_key_from_serial_date, generate_key_v1

logger = logging.getLogger(__name__)

# 已知的海康威视服务域名白名单
# 微信域名（weixin.qq.com）已加入白名单，因为海康威视在中国通过微信公众号重定向分发密钥。
# Known Hikvision service domain allowlist.
# WeChat (weixin.qq.com) is included because Hikvision's password reset process in China
# redirects through WeChat official accounts for key delivery.
HIKVISION_DOMAINS = [
    "hikvision.com",
    "hikconnect.com",
    "hik-connect.com",
    "lechange.com",
    "ezviz.com",
    "weixin.qq.com",  # WeChat — used by Hikvision for key distribution in China / 微信公众号密钥分发
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

# URL 查询参数中可能包含设备序列号的参数名
# URL query parameter names that may contain a device serial number
_SERIAL_PARAM_NAMES = [
    "sn",
    "serialNumber",
    "deviceSerial",
    "serial",
    "device",
    "deviceSn",
    "device_serial",
    "deviceno",
    "devicesn",
    "deviceNum",
]

# URL 查询参数中可能包含日期的参数名
# URL query parameter names that may contain a device date
_DATE_PARAM_NAMES = [
    "date",
    "time",
    "startTime",
    "deviceDate",
    "device_date",
    "resetDate",
    "createTime",
]

# HTML/JS 响应中可能包含二级跳转 URL 的正则表达式
# Regex patterns for finding secondary redirect URLs inside HTML/JS responses
_SECONDARY_URL_PATTERNS = [
    r'href=["\']+(https?://[^\s"\'<>]{10,})',
    r'"url"\s*:\s*"(https?://[^"]{10,})"',
    r"'url'\s*:\s*'(https?://[^']{10,})'",
    r'window\.location(?:\.href)?\s*=\s*["\']+(https?://[^"\']{10,})',
    r'location\.replace\(["\']+(https?://[^"\']{10,})',
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
      1. URL（http/https）→ 请求并提取密钥；若失败则尝试从 URL 参数离线生成
         URL (http/https) → fetch and extract key; if that fails, try offline from URL params
      2. 多行设备数据字符串（如 "B:DS-XXXX..."）→ 解析后尝试所有可用算法
         Multi-line device data string (e.g. "B:DS-XXXX...") → parse and try all available algorithms
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


def _parse_sadp_qr_fields(content: str) -> dict:
    """
    解析 SADP 导出的多行 QR 码数据，提取所有可用字段。
    Parse the multi-line SADP QR code data and extract all available fields.

    SADP 二维码可能包含如下格式 / SADP QR may contain formats like:
      B:DS-7908HQH-SH12345678                   (old simple format)
      B:DS-7908HQH-SH12345678\\r\\nDate:20240315  (with date)

    Returns:
        字段字典，可包含 serial, date 等键
        Dict with extracted fields (serial, date, etc.)
    """
    fields: dict = {}

    # 规范化换行符（SADP 使用 \\r\\n 或 \\n）/ Normalize line endings
    lines = re.split(r'[\r\n]+', content.strip())

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # 第一行通常是 "B:DS-..." 格式 / First line is usually "B:DS-..." format
        if i == 0:
            m = re.match(r'^[A-Z]?:?\s*(DS-[A-Z0-9\-]+)', line, re.IGNORECASE)
            if m:
                fields["serial"] = m.group(1)
                continue
            m = re.match(r'^(DS-[A-Z0-9\-]+)', line, re.IGNORECASE)
            if m:
                fields["serial"] = m.group(1)
                continue

        # 键值对格式（不区分大小写）/ Key-value pairs (case-insensitive)
        kv = re.match(r'^([A-Za-z_]+)\s*[:=]\s*(.+)$', line)
        if kv:
            key = kv.group(1).lower().replace("_", "")
            val = kv.group(2).strip()
            if key in ("date", "devicedate", "resetdate", "time"):
                fields["date"] = val.replace("-", "")
            elif key in ("verifycode", "verifcode", "verificationcode", "safetycode", "safecode"):
                fields["verify_code"] = val
            elif key in ("sn", "serial", "serialnumber", "deviceserial"):
                fields["serial"] = val
            elif key == "version":
                fields["version"] = val
            elif key == "devicetype":
                fields["device_type"] = val
            continue

        # 备用：在任意行中查找序列号 / Fallback: find serial in any line
        if "serial" not in fields:
            m = re.search(r'(DS-[A-Z0-9\-]+)', line, re.IGNORECASE)
            if m:
                fields["serial"] = m.group(1)

        # 备用：在任意行中查找日期（8位数字）/ Fallback: find date in any line
        if "date" not in fields:
            m = re.search(r'(\d{8})', line)
            if m:
                fields["date"] = m.group(1)

    return fields


def _process_device_data(content: str) -> ResetKeyResult:
    """
    处理设备数据格式的 QR 内容，尝试提取序列号并生成密钥。
    Process device data format QR code content.

    解析 SADP 多行格式，按以下优先级尝试生成密钥 / Parses SADP multi-line format,
    tries key generation in this order:
      1. 若含日期 → 使用离线算法 (序列号 + 日期 → 安全码)
         If date present → use offline algorithm (serial + date → security code)
      2. 仅有序列号 → 使用今日日期 + 离线算法，并提示用户确认日期
         Serial only → use today's date + offline algorithm, warn user to confirm date
    """
    fields = _parse_sadp_qr_fields(content)
    serial = fields.get("serial")
    date_str = fields.get("date")

    # 兜底：直接从原始内容搜索序列号 / Fallback: search raw content
    if not serial:
        serial_match = re.search(r'(DS-[A-Z0-9\-]+)', content, re.IGNORECASE)
        if serial_match:
            serial = serial_match.group(1)

    if not serial:
        return ResetKeyResult(
            qr_content=content,
            method="raw",
            error=(
                "Device data format detected but could not extract serial number. "
                "Please provide the serial number and date for offline key generation."
            ),
        )

    # 1. 使用离线算法（日期）/ Use offline algorithm (date) if available
    today = date.today()
    if date_str:
        try:
            key = generate_key_from_serial_date(serial, date_str)
            return ResetKeyResult(
                key=key,
                qr_content=content,
                method="offline_v1",
                error=(
                    f"Generated key using offline algorithm for serial '{serial}' "
                    f"with date '{date_str}'. "
                    "Note: If this key does not work, please confirm the exact device date "
                    "shown in SADP."
                ),
            )
        except ValueError:
            pass

    # 2. 仅序列号，使用今日日期 / Serial only, fall back to today's date
    key = generate_key_v1(serial, today)
    return ResetKeyResult(
        key=key,
        qr_content=content,
        method="offline_v1",
        error=(
            f"Generated key using offline algorithm for serial '{serial}' "
            f"with today's date ({today}). "
            "Note: If this key does not work, please provide the exact device date shown in SADP "
            "via the 'Offline Key Generation' tab."
        ),
    )


def parse_sadp_device_file(file_content: str) -> list[dict]:
    """
    解析 SADP 导出的设备特征文件（二进制格式），提取设备序列号。
    Parse a SADP-exported device characteristic file (binary format) and extract device serial.

    SADP 导出的设备特征文件实际为二进制格式（尽管扩展名为 .xml），结构如下：
    The SADP device characteristic file is binary (despite the .xml extension):
      - 前 4 字节：文件版本号（小端序 uint32，如 03 00 00 00 = v3）
        First 4 bytes: version (little-endian uint32, e.g. 03 00 00 00 = v3)
      - 中间：加密/编码的设备挑战数据
        Middle: encrypted/encoded challenge data
      - 尾部：ASCII 明文设备序列号（如 DS-2CD3525FV3-IT20231211AACHAX8748548）
        Tail: ASCII plaintext device serial (e.g. DS-2CD3525FV3-IT20231211AACHAX8748548)

    Args:
        file_content: SADP 导出文件的内容（已解码为字符串）
                      Content of the SADP-exported file (decoded to string)

    Returns:
        包含设备信息的字典列表（每台设备一条）。每个字典至少含 serial 键。
        List of device info dicts (one per device). Each dict has at least a 'serial' key.

    Raises:
        ValueError: 文件无效或未找到设备序列号
                    If file is invalid or no serial number found
    """
    content = file_content.strip()
    if not content:
        raise ValueError(
            "Empty file. "
            "Please ensure this is a valid SADP device characteristic file."
        )

    # ------------------------------------------------------------------
    # 尝试从文件内容中提取设备序列号
    # Try to extract device serial number(s) from the file content.
    # The serial is typically embedded as readable ASCII in the binary data.
    # ------------------------------------------------------------------

    # 常见海康序列号模式（含制造日期，如 DS-2CD2T45G0P-I20190101XXXX）
    # Primary pattern: full serial with embedded 8-digit manufacturing date.
    # This is strict to avoid matching random base64 fragments that happen
    # to contain "DS-".
    serial_pattern = re.compile(
        r'(?:i?DS-[A-Z0-9/()_-]+(?:\d{8,})[A-Z0-9]+)',
        re.IGNORECASE,
    )
    matches = serial_pattern.findall(content)

    if not matches:
        # 备用策略：较短的 DS- 开头串（不含制造日期，如旧设备或截断的序列号）
        # Fallback: shorter DS- prefixed strings without the date requirement,
        # for older devices or truncated serials where the full format isn't present.
        fallback_pattern = re.compile(r'((?:i?DS-)[A-Z0-9/()_-]{5,})', re.IGNORECASE)
        matches = fallback_pattern.findall(content)

    if not matches:
        raise ValueError(
            "No device serial number found in the file. "
            "Please ensure this is a valid SADP device characteristic file "
            "(exported from SADP tool via 'Export' in the password reset dialog)."
        )

    # 去重（同一文件中可能多次出现同一序列号）/ Deduplicate
    seen: set[str] = set()
    devices: list[dict] = []
    for serial in matches:
        if serial not in seen:
            seen.add(serial)
            devices.append({"serial": serial})

    return devices


async def process_sadp_device_file(file_content: str) -> list["ResetKeyResult"]:
    """
    处理 SADP 设备特征文件，提取序列号并为每台设备生成重置密钥。
    Process a SADP device characteristic file, extract serial numbers, and generate reset keys.

    对于每个找到的设备，使用今日日期 + 离线算法生成密钥。
    For each device found, generates a key using today's date + offline algorithm.

    Args:
        file_content: SADP 导出文件的内容 / SADP-exported file content

    Returns:
        每台设备对应一个 ResetKeyResult 的列表
        List of ResetKeyResult, one per device
    """
    try:
        devices = parse_sadp_device_file(file_content)
    except ValueError as exc:
        return [ResetKeyResult(error=str(exc), method="sadp_file")]

    results = []
    today = date.today()
    today_str = today.strftime("%Y%m%d")

    for dev in devices:
        serial = dev["serial"]
        key = generate_key_v1(serial, today)
        results.append(ResetKeyResult(
            key=key,
            qr_content=f"Serial: {serial}",
            method="offline_v1_from_file",
            error=(
                f"Extracted serial '{serial}' from device file, generated key "
                f"using today's date ({today_str}). "
                "Note: If this key does not work, use the 'Offline Key Generation' tab "
                "and enter the exact device date shown in SADP."
            ),
        ))

    return results


def _extract_serial_from_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    从 URL 查询参数中尝试提取设备序列号和日期。
    Try to extract the device serial number and date from a URL's query parameters.

    处理以下 SADP 导出 URL 格式 / Handles common SADP export URL formats:
      - ?sn=DS-XXXX&date=YYYYMMDD  (直接参数 / plain parameters)
      - ?data=BASE64({"sn":"DS-XXXX","date":"YYYYMMDD"})  (base64 编码 JSON / base64-encoded JSON)
      - URL 路径中包含序列号 / Serial number embedded in URL path

    Args:
        url: The URL string to parse

    Returns:
        (serial, date_str) tuple; either value may be None if not found.
        date_str is in YYYYMMDD format when found.
    """
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)

        serial: Optional[str] = None
        date_str: Optional[str] = None

        # ------------------------------------------------------------------
        # 1. 在已知参数名中查找序列号 / Look for serial in known param names
        # ------------------------------------------------------------------
        for name in _SERIAL_PARAM_NAMES:
            # parse_qs is case-sensitive; try original, lower, and upper
            for variant in (name, name.lower(), name.upper()):
                for v in params.get(variant, []):
                    if re.match(r'^DS-[A-Z0-9\-]+', v, re.IGNORECASE):
                        serial = v
                        break
                if serial:
                    break
            if serial:
                break

        # ------------------------------------------------------------------
        # 2. 在已知参数名中查找日期 / Look for date in known param names
        # ------------------------------------------------------------------
        for name in _DATE_PARAM_NAMES:
            for variant in (name, name.lower(), name.upper()):
                for v in params.get(variant, []):
                    v_clean = v.replace("-", "")
                    if len(v_clean) == 8 and v_clean.isdigit():
                        date_str = v_clean
                        break
                if date_str:
                    break
            if date_str:
                break

        # ------------------------------------------------------------------
        # 3. URL 路径中查找序列号 / Look for serial in URL path segments
        # ------------------------------------------------------------------
        if not serial:
            path_m = re.search(r'(DS-[A-Z0-9\-]+)', parsed.path, re.IGNORECASE)
            if path_m:
                serial = path_m.group(1)

        # ------------------------------------------------------------------
        # 4. 尝试 base64 解码参数以提取序列号/日期
        #    Try base64-decoding param values to extract serial/date
        # ------------------------------------------------------------------
        if not serial:
            for values_list in params.values():
                for v in values_list:
                    if len(v) < 8:
                        continue
                    try:
                        # base64 requires input length to be a multiple of 4; add "=" padding
                        padding_needed = (4 - len(v) % 4) % 4
                        padded = v + "=" * padding_needed
                        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")

                        # Try to find serial in raw decoded string
                        sn_m = re.search(r'(DS-[A-Z0-9\-]+)', decoded, re.IGNORECASE)
                        if sn_m:
                            serial = sn_m.group(1)
                            # Also look for a date in the same decoded payload
                            if not date_str:
                                date_m = re.search(r'(\d{8})', decoded)
                                if date_m:
                                    date_str = date_m.group(1)

                        # Try to parse decoded string as JSON
                        if not serial:
                            try:
                                data = json.loads(decoded)
                                for k in _SERIAL_PARAM_NAMES:
                                    val = data.get(k) or data.get(k.lower()) or data.get(k.upper())
                                    if val and re.match(r'^DS-[A-Z0-9\-]+', str(val), re.IGNORECASE):
                                        serial = str(val)
                                        break
                                if not date_str:
                                    for k in _DATE_PARAM_NAMES:
                                        val = data.get(k) or data.get(k.lower()) or data.get(k.upper())
                                        if val:
                                            v_clean = str(val).replace("-", "")
                                            if len(v_clean) == 8 and v_clean.isdigit():
                                                date_str = v_clean
                                                break
                            except (json.JSONDecodeError, TypeError, AttributeError):
                                pass

                    except Exception:
                        pass

                    if serial:
                        break
                if serial:
                    break

        return serial, date_str

    except Exception:
        return None, None


def _find_redirect_urls(content: str) -> list[str]:
    """
    从 HTML/JS 响应内容中提取可能包含密钥的二级跳转 URL。
    Find secondary redirect URLs inside an HTML/JS response that may lead to the key.

    主要用于提取海康威视重置页面中嵌入的微信公众号 URL。
    Primarily used to extract WeChat URLs embedded in Hikvision's reset landing pages.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for pattern in _SECONDARY_URL_PATTERNS:
        for m in re.finditer(pattern, content, re.IGNORECASE):
            url = m.group(1).strip()
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


async def _process_url(url: str) -> ResetKeyResult:
    """
    请求 QR 码中的 URL 并尝试提取重置密钥。
    Fetch a URL from the QR code and attempt to extract the reset key.

    处理策略（按顺序）/ Processing strategy (in order):
      1. 验证域名白名单 / Validate against domain allowlist (SSRF protection)
      2. 请求 URL 并从响应中提取密钥 / Fetch URL and extract key from response
      3. 若响应中无密钥，扫描响应内容中的二级 URL 并尝试获取
         If no key in response, scan response for secondary URLs and try those
      4. 若请求返回 403 或网络错误，尝试从 URL 参数提取序列号进行离线生成
         If 403 or network error, try extracting serial from URL params for offline keygen

    安全措施：仅允许请求白名单内的域名，防止 SSRF 攻击。
    Security: Only URLs belonging to known allowlisted domains are fetched to prevent SSRF.
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
    is_allowed = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in HIKVISION_DOMAINS
    )

    if not is_allowed:
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

        # 未直接找到密钥 → 扫描响应中的二级 URL（如微信链接）并尝试获取
        # Key not found directly → scan response for secondary URLs (e.g. WeChat links)
        secondary_result = await _try_secondary_urls(url, content)
        if secondary_result is not None:
            return secondary_result

        # 仍未获取到密钥：提示用户使用离线方式 / Still no key: guide to offline mode
        offline = _try_offline_from_url(url)
        if offline is not None:
            return offline

        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=(
                "The Hikvision server was reached but no reset key was found in its response. "
                "The key may require interactive WeChat authentication that cannot be automated. "
                "Please try the 'Offline Key Generation' tab — enter the serial number and "
                "device date shown in SADP."
            ),
            raw_response=content[:2000],
        )

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # 403 或其他 HTTP 错误：先尝试从 URL 参数离线提取序列号
        # 403 or other HTTP error: first try offline extraction from URL params
        offline = _try_offline_from_url(url)
        if offline is not None:
            return offline
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=(
                f"HTTP {status} error when fetching the Hikvision reset URL. "
                "The server could not be reached from this network (it may be restricted to "
                "China/internal networks). "
                "Please use the 'Offline Key Generation' tab: enter the serial number and "
                "device date shown in SADP."
            ),
        )
    except httpx.RequestError as exc:
        # 网络错误：尝试从 URL 参数离线提取序列号
        # Network error: try offline extraction from URL params
        offline = _try_offline_from_url(url)
        if offline is not None:
            return offline
        return ResetKeyResult(
            qr_content=url,
            method="url_fetch",
            error=(
                f"Network error when fetching the Hikvision reset URL: {exc}. "
                "Please use the 'Offline Key Generation' tab: enter the serial number and "
                "device date shown in SADP."
            ),
        )


def _try_offline_from_url(url: str) -> Optional["ResetKeyResult"]:
    """
    尝试从 URL 查询参数中提取序列号，并使用离线算法生成密钥。
    Try to extract a serial number from URL query parameters and generate a key offline.

    用于 URL 请求失败（如 403）时的本地解析回退。
    Used as a local-parsing fallback when the URL fetch fails (e.g. 403).

    Returns ResetKeyResult if a serial was found, None otherwise.
    """
    serial, date_str = _extract_serial_from_url(url)
    if not serial:
        return None

    today = date.today()
    if date_str:
        try:
            key = generate_key_from_serial_date(serial, date_str)
            return ResetKeyResult(
                key=key,
                qr_content=url,
                method="offline_from_url",
                error=(
                    f"URL fetch failed. Generated key offline using serial '{serial}' "
                    f"and date '{date_str}' extracted from the URL. "
                    "Note: This works for older firmware only. "
                    "If this key does not work, please check the device date in SADP."
                ),
            )
        except ValueError:
            pass

    # 日期未在 URL 中找到，使用今天日期
    # Date not found in URL, fall back to today's date
    key = generate_key_v1(serial, today)
    return ResetKeyResult(
        key=key,
        qr_content=url,
        method="offline_from_url",
        error=(
            f"URL fetch failed. Generated key offline using serial '{serial}' "
            f"extracted from the URL with today's date ({today}). "
            "Note: This works for older firmware only. "
            "If this key does not work, please provide the exact device date shown in SADP."
        ),
    )


async def _try_secondary_urls(
    original_url: str, response_content: str
) -> Optional["ResetKeyResult"]:
    """
    从 HTML 响应中提取二级 URL（如微信链接），并尝试从中获取密钥。
    Extract secondary URLs (e.g. WeChat links) from an HTML response and try to get the key.

    用于处理海康威视重置页面跳转到微信公众号的场景。
    Handles the case where Hikvision reset pages redirect to WeChat official accounts.
    """
    candidate_urls = _find_redirect_urls(response_content)
    for sec_url in candidate_urls:
        try:
            sec_parsed = urlparse(sec_url)
            sec_hostname = sec_parsed.hostname or ""
        except Exception:
            continue

        # 仅跟踪白名单域名的二级 URL / Only follow secondary URLs from allowlisted domains
        is_allowed = any(
            sec_hostname == domain or sec_hostname.endswith(f".{domain}")
            for domain in HIKVISION_DOMAINS
        )
        if not is_allowed:
            logger.debug("Skipping secondary URL (non-allowlisted domain): %s", sec_url)
            continue
        if sec_parsed.scheme not in ("http", "https"):
            continue

        logger.info("Trying secondary URL from response: %s://%s", sec_parsed.scheme, sec_hostname)
        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                headers={"User-Agent": MOBILE_UA},
                follow_redirects=True,
            ) as client:
                sec_response = await client.get(sec_url)
                sec_response.raise_for_status()
                sec_content = sec_response.text

            key = _extract_key_from_response(sec_content)
            if key:
                return ResetKeyResult(
                    key=key,
                    qr_content=original_url,
                    method="url_fetch_via_redirect",
                    raw_response=sec_content[:2000],
                )
        except Exception as exc:
            logger.debug("Secondary URL fetch failed for %s: %s", sec_url, exc)

    return None


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
    使用离线算法 v1 生成重置密钥（序列号 + 日期）。
    Generate a reset key using offline algorithm v1 (serial number + date).

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
