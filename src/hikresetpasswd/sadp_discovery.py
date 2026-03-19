"""
海康威视 SADP 设备发现模块
Hikvision SADP (Search Active Devices Protocol) Discovery Module

通过 UDP 多播在局域网中发现海康威视设备，获取设备信息（序列号、固件版本、启动时间、IP 等）。
Discovers Hikvision devices on the local network via UDP multicast,
retrieving device info (serial number, firmware version, boot time, IP, etc.).

协议说明 / Protocol description:
  - 向 239.255.255.250:37020 发送 XML 格式的 Probe inquiry 包
    Send an XML Probe inquiry packet to 239.255.255.250:37020
  - 设备以 XML 格式响应，包含设备详细信息
    Devices respond with XML containing device details
  - 解析响应以提取序列号、固件版本、启动时间等
    Parse responses to extract serial number, firmware version, boot time, etc.

用途 / Purpose:
  解决用户无法获取设备时间的问题，自动发现设备并获取所需信息。
  Solves the problem of users not being able to get device time by auto-discovering
  devices and retrieving the necessary information.
"""

import asyncio
import logging
import re
import socket
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# SADP 多播地址和端口 / SADP multicast address and port
SADP_MULTICAST_ADDR = "239.255.255.250"
SADP_PORT = 37020

# 默认扫描超时（秒）/ Default scan timeout in seconds
DEFAULT_TIMEOUT = 5

# 固件版本阈值：低于此版本支持离线密钥生成
# Firmware version threshold: offline keygen works below this version
FIRMWARE_THRESHOLD = (5, 3, 0)


@dataclass
class DiscoveredDevice:
    """
    SADP 发现的设备信息。
    Device information discovered via SADP.
    """

    # 设备 IP 地址 / Device IP address
    ip_address: str = ""
    # 设备序列号 / Device serial number
    serial_number: str = ""
    # 设备描述/型号 / Device model/description
    device_description: str = ""
    # 软件/固件版本 / Software/firmware version
    software_version: str = ""
    # DSP 版本 / DSP version
    dsp_version: str = ""
    # 设备启动时间（即设备内部时间）/ Device boot time (i.e. device internal time)
    boot_time: str = ""
    # MAC 地址 / MAC address
    mac: str = ""
    # 子网掩码 / Subnet mask
    subnet_mask: str = ""
    # 网关 / Gateway
    gateway: str = ""
    # HTTP 端口 / HTTP port
    http_port: str = ""
    # 命令端口 / Command port
    command_port: str = ""
    # DHCP 是否启用 / Whether DHCP is enabled
    dhcp: str = ""
    # 模拟通道数 / Number of analog channels
    analog_channels: str = ""
    # 数字通道数 / Number of digital channels
    digital_channels: str = ""
    # 是否支持离线密钥重置 / Whether offline key reset is supported
    supports_offline_reset: bool = False
    # 固件版本过高的提示 / Warning for firmware too new
    firmware_note: str = ""
    # 所有原始字段 / All raw fields from the SADP response
    raw_fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为字典 / Convert to dict for JSON serialization."""
        return {
            "ip_address": self.ip_address,
            "serial_number": self.serial_number,
            "device_description": self.device_description,
            "software_version": self.software_version,
            "dsp_version": self.dsp_version,
            "boot_time": self.boot_time,
            "mac": self.mac,
            "subnet_mask": self.subnet_mask,
            "gateway": self.gateway,
            "http_port": self.http_port,
            "command_port": self.command_port,
            "dhcp": self.dhcp,
            "analog_channels": self.analog_channels,
            "digital_channels": self.digital_channels,
            "supports_offline_reset": self.supports_offline_reset,
            "firmware_note": self.firmware_note,
        }


def _build_probe_xml() -> bytes:
    """
    构建 SADP 发现探测包的 XML 内容。
    Build the XML content for a SADP discovery probe packet.

    Returns:
        UTF-8 编码的 XML 探测包 / UTF-8 encoded XML probe packet
    """
    probe_uuid = str(uuid.uuid4()).upper()
    xml_str = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f"<Probe><Uuid>{probe_uuid}</Uuid><Types>inquiry</Types></Probe>"
    )
    return xml_str.encode("utf-8")


def parse_firmware_version(version_str: str) -> Optional[tuple[int, ...]]:
    """
    从固件版本字符串中提取版本号元组。
    Extract a version tuple from a firmware version string.

    支持的格式 / Supported formats:
      - "V5.2.5build 141201" → (5, 2, 5)
      - "V7.3.0" → (7, 3, 0)
      - "5.3.0" → (5, 3, 0)

    Args:
        version_str: 固件版本字符串 / Firmware version string

    Returns:
        版本号元组，解析失败返回 None / Version tuple, or None if parsing fails
    """
    if not version_str:
        return None
    # 匹配 V?.?.? 或 ?.?.? 格式 / Match V?.?.? or ?.?.? format
    m = re.search(r"[Vv]?(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if m:
        parts = [int(m.group(1)), int(m.group(2))]
        if m.group(3) is not None:
            parts.append(int(m.group(3)))
        else:
            parts.append(0)
        return tuple(parts)
    return None


def check_firmware_support(version_str: str) -> tuple[bool, str]:
    """
    检查固件版本是否支持离线密钥重置。
    Check if the firmware version supports offline key reset.

    Args:
        version_str: 固件版本字符串（如 SoftwareVersion 字段）
                     Firmware version string (e.g. from SoftwareVersion field)

    Returns:
        (supports_offline, note) 元组：
          - supports_offline: True 如果固件 < 5.3.0 / True if firmware < 5.3.0
          - note: 说明信息 / Descriptive note
    """
    parsed = parse_firmware_version(version_str)
    if parsed is None:
        return False, (
            f"无法解析固件版本 '{version_str}'，建议通过海康威视官方渠道重置密码。"
            f" / Cannot parse firmware version '{version_str}'. "
            "Recommend using official Hikvision channels for password reset."
        )

    if parsed < FIRMWARE_THRESHOLD:
        return True, (
            f"固件版本 {version_str} 支持离线密钥生成（< 5.3.0）。"
            f" / Firmware {version_str} supports offline key generation (< 5.3.0)."
        )

    return False, (
        f"固件版本 {version_str} 不支持离线密钥生成（≥ 5.3.0）。"
        "请通过海康威视官方渠道重置："
        "①微信公众号「海康威视客户服务」→贴心服务→密码重置；"
        "②拨打 400-700-5998；"
        "③使用 SADP 导出设备特征文件发送给技术支持获取重置文件。"
        f" / Firmware {version_str} does NOT support offline key generation (≥ 5.3.0). "
        "Please use official Hikvision channels: "
        "① WeChat '海康威视客户服务' → Service → Password Reset; "
        "② Call 400-700-5998; "
        "③ Export device characteristic file from SADP and send to Hikvision support."
    )


def _parse_sadp_response(data: bytes, addr: tuple) -> Optional[DiscoveredDevice]:
    """
    解析 SADP 响应数据包。
    Parse a SADP response packet.

    Args:
        data: 原始 UDP 数据 / Raw UDP data
        addr: 发送者地址 (ip, port) / Sender address

    Returns:
        解析出的设备信息，或 None（如果无法解析）
        Parsed device info, or None if parsing fails
    """
    try:
        # 尝试解码为 UTF-8 XML / Try to decode as UTF-8 XML
        xml_str = data.decode("utf-8", errors="ignore")

        # 查找 XML 开头（跳过可能的二进制头部）
        # Find XML start (skip possible binary header)
        xml_start = xml_str.find("<?xml")
        if xml_start < 0:
            xml_start = xml_str.find("<ProbeMatch")
        if xml_start < 0:
            # 有些设备不带 XML 声明 / Some devices omit XML declaration
            xml_start = xml_str.find("<")

        if xml_start < 0:
            return None

        xml_content = xml_str[xml_start:]
        root = ET.fromstring(xml_content)

        # 提取所有子元素到字典 / Extract all child elements to dict
        fields: dict[str, str] = {}
        for child in root:
            tag = child.tag
            text = (child.text or "").strip()
            if text:
                fields[tag] = text

        # 如果没有 DeviceSN 字段，可能不是有效的设备响应
        # If no DeviceSN field, this may not be a valid device response
        serial = fields.get("DeviceSN", "")
        if not serial:
            return None

        software_version = fields.get("SoftwareVersion", "")
        supports_offline, firmware_note = check_firmware_support(software_version)

        device = DiscoveredDevice(
            ip_address=fields.get("IPv4Address", addr[0]),
            serial_number=serial,
            device_description=fields.get("DeviceDescription", ""),
            software_version=software_version,
            dsp_version=fields.get("DSPVersion", ""),
            boot_time=fields.get("BootTime", fields.get("DateTime", "")),
            mac=fields.get("MAC", ""),
            subnet_mask=fields.get("IPv4SubnetMask", ""),
            gateway=fields.get("IPv4Gateway", ""),
            http_port=fields.get("HttpPort", ""),
            command_port=fields.get("CommandPort", ""),
            dhcp=fields.get("DHCP", ""),
            analog_channels=fields.get("AnalogChannelNum", ""),
            digital_channels=fields.get("DigitalChannelNum", ""),
            supports_offline_reset=supports_offline,
            firmware_note=firmware_note,
            raw_fields=fields,
        )
        return device

    except ET.ParseError:
        logger.debug("Failed to parse SADP XML response from %s", addr[0])
        return None
    except Exception as exc:
        logger.debug("Error parsing SADP response from %s: %s", addr[0], exc)
        return None


def discover_devices_sync(timeout: float = DEFAULT_TIMEOUT) -> list[DiscoveredDevice]:
    """
    同步方式发现局域网中的海康威视设备。
    Discover Hikvision devices on the local network synchronously.

    通过 UDP 多播发送 SADP Probe 探测包，收集设备响应。
    Sends a SADP Probe via UDP multicast and collects device responses.

    Args:
        timeout: 等待设备响应的超时时间（秒）/ Timeout for waiting for responses (seconds)

    Returns:
        发现的设备列表 / List of discovered devices
    """
    devices: list[DiscoveredDevice] = []
    seen_serials: set[str] = set()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 设置多播 TTL / Set multicast TTL
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)

        # 发送探测包 / Send probe packet
        probe = _build_probe_xml()
        sock.sendto(probe, (SADP_MULTICAST_ADDR, SADP_PORT))
        logger.info(
            "SADP discovery probe sent to %s:%d (timeout: %ss)",
            SADP_MULTICAST_ADDR,
            SADP_PORT,
            timeout,
        )

        # 持续接收响应直到超时 / Keep receiving responses until timeout
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                device = _parse_sadp_response(data, addr)
                if device and device.serial_number not in seen_serials:
                    seen_serials.add(device.serial_number)
                    devices.append(device)
                    logger.info(
                        "Discovered device: %s (%s) at %s - firmware: %s",
                        device.serial_number,
                        device.device_description,
                        device.ip_address,
                        device.software_version,
                    )
            except TimeoutError:
                break

    except OSError as exc:
        logger.warning("SADP discovery socket error: %s", exc)
    finally:
        try:
            sock.close()
        except Exception:
            pass

    logger.info("SADP discovery complete: found %d device(s)", len(devices))
    return devices


async def discover_devices(timeout: float = DEFAULT_TIMEOUT) -> list[DiscoveredDevice]:
    """
    异步方式发现局域网中的海康威视设备。
    Discover Hikvision devices on the local network asynchronously.

    在线程池中运行同步 UDP 操作以避免阻塞事件循环。
    Runs the synchronous UDP operations in a thread pool to avoid blocking the event loop.

    Args:
        timeout: 等待设备响应的超时时间（秒）/ Timeout for waiting for responses (seconds)

    Returns:
        发现的设备列表 / List of discovered devices
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, discover_devices_sync, timeout)
