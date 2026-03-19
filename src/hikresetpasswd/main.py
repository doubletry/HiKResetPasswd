"""
海康威视密码重置工具 - 后端主应用
Hikvision Password Reset Tool - Backend Main Application

FastAPI 应用，提供以下功能 / FastAPI app providing:
  1. 接收并解码 QR 码图片 / Accept and decode QR code images
  2. 从 QR 内容中尝试获取重置密钥 / Attempt to obtain reset key from QR content
  3. 离线密钥生成（序列号+日期）/ Offline key generation (serial + date)
  4. 接收 SADP 设备特征文件并解析生成密钥 / Accept SADP device characteristic files
  5. SADP 局域网设备发现（自动获取序列号、固件版本、设备时间）
     SADP LAN device discovery (auto-detect serial, firmware version, device time)
  6. 生产模式下托管前端静态文件 / Serve frontend static files in production mode
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .qr_decoder import QRCodeDecodeError, decode_qr_from_bytes
from .sadp_discovery import discover_devices
from .service import (
    generate_key_offline,
    process_qr_content,
    process_sadp_device_file,
)

# 前端构建输出目录（生产模式下由 FastAPI 托管）
# Frontend build output directory (served by FastAPI in production mode)
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

# 根据配置设置日志级别 / Set log level from config
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 / Application lifespan handler."""
    logger.info(
        "Starting Hikvision Password Reset Backend on %s:%s",
        settings.host,
        settings.port,
    )
    yield
    logger.info("Shutting down Hikvision Password Reset Backend")


app = FastAPI(
    title="Hikvision Password Reset Tool",
    description=(
        "海康威视摄像头密码重置工具 / "
        "A tool to help reset Hikvision camera passwords by processing "
        "SADP-generated QR codes and obtaining reset keys."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件：允许来自前端的跨域请求
# CORS middleware: allow cross-origin requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic 模型 / Pydantic models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """健康检查响应 / Health check response."""

    status: str
    message: str


class KeyRequest(BaseModel):
    """离线密钥生成请求体（序列号 + 日期）/ Offline key generation request body (serial + date)."""

    serial: str = Field(..., description="Device serial number from SADP / SADP 中的设备序列号")
    date: str = Field(
        ...,
        description=(
            "Device date from SADP in YYYYMMDD or YYYY-MM-DD format / "
            "SADP 中显示的设备日期，格式 YYYYMMDD 或 YYYY-MM-DD"
        ),
        examples=["20240315", "2024-03-15"],
    )


class QRContentRequest(BaseModel):
    """已解码 QR 内容请求体 / Pre-decoded QR content request body."""

    qr_content: str = Field(..., description="Raw QR code content string / QR 码原始文本内容")


class KeyResponse(BaseModel):
    """密钥响应体 / Key response body."""

    key: str | None = Field(None, description="Reset key if successfully obtained / 获取到的重置密钥")
    qr_content: str | None = Field(None, description="Decoded QR code content / 解码后的 QR 内容")
    method: str | None = Field(None, description="Method used to obtain the key / 获取密钥的方式")
    error: str | None = Field(None, description="Error message if key could not be obtained / 错误信息")
    raw_response: str | None = Field(None, description="Raw response from server if applicable / 服务器原始响应")
    waf_blocked: bool = Field(False, description="Whether request was blocked by Hikvision WAF / 是否被海康 WAF 拦截")


class SADPFileResponse(BaseModel):
    """SADP 设备文件解析结果响应体 / SADP device file parse result response body."""

    devices: list[KeyResponse] = Field(
        default_factory=list,
        description="Results for each device found in the SADP file / 设备特征文件中每台设备的结果",
    )
    count: int = Field(0, description="Number of devices found / 找到的设备数量")
    error: str | None = Field(None, description="File-level error (if file could not be parsed) / 文件级错误信息")


class DiscoveredDeviceResponse(BaseModel):
    """SADP 发现的单个设备信息 / Single device discovered via SADP."""

    ip_address: str = Field("", description="Device IP address / 设备 IP 地址")
    serial_number: str = Field("", description="Device serial number / 设备序列号")
    device_description: str = Field("", description="Device model/description / 设备型号")
    software_version: str = Field("", description="Firmware version / 固件版本")
    dsp_version: str = Field("", description="DSP version / DSP 版本")
    boot_time: str = Field("", description="Device boot time (internal clock) / 设备启动时间（内部时钟）")
    mac: str = Field("", description="MAC address / MAC 地址")
    subnet_mask: str = Field("", description="Subnet mask / 子网掩码")
    gateway: str = Field("", description="Gateway / 网关")
    http_port: str = Field("", description="HTTP port / HTTP 端口")
    command_port: str = Field("", description="Command port / 命令端口")
    dhcp: str = Field("", description="DHCP enabled / DHCP 是否启用")
    analog_channels: str = Field("", description="Number of analog channels / 模拟通道数")
    digital_channels: str = Field("", description="Number of digital channels / 数字通道数")
    supports_offline_reset: bool = Field(False, description="Whether offline reset is supported / 是否支持离线重置")
    firmware_note: str = Field("", description="Firmware support note / 固件版本说明")


class SADPDiscoveryResponse(BaseModel):
    """SADP 局域网设备发现结果 / SADP LAN device discovery result."""

    devices: list[DiscoveredDeviceResponse] = Field(
        default_factory=list,
        description="Discovered devices / 发现的设备列表",
    )
    count: int = Field(0, description="Number of devices found / 发现的设备数量")
    error: str | None = Field(None, description="Discovery error / 发现过程中的错误")


# ---------------------------------------------------------------------------
# API 端点 / API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查端点。
    Health check endpoint.
    """
    return HealthResponse(status="ok", message="Hikvision Password Reset Backend is running")


@app.post("/api/qr/upload", response_model=KeyResponse)
async def upload_qr_image(file: UploadFile = File(...)):
    """
    上传 QR 码截图，解码并尝试获取重置密钥。
    Upload a QR code screenshot, decode it, and attempt to get the reset key.

    支持的图片格式 / Supported image formats: PNG, JPEG, BMP, GIF, TIFF 等
    """
    # 验证上传文件是图片 / Validate uploaded file is an image
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"File must be an image. Got: {file.content_type}",
        )

    image_bytes = await file.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # 1. 解码 QR 码 / Decode the QR code
    try:
        qr_content = decode_qr_from_bytes(image_bytes)
    except QRCodeDecodeError as exc:
        return KeyResponse(error=str(exc))

    # 2. 处理 QR 内容，尝试获取密钥 / Process QR content to get the key
    result = await process_qr_content(qr_content)
    return KeyResponse(**result.to_dict())


@app.post("/api/qr/content", response_model=KeyResponse)
async def process_qr_content_endpoint(request: QRContentRequest):
    """
    处理已解码的 QR 文本内容，尝试获取重置密钥。
    Process pre-decoded QR text content and attempt to get the reset key.

    适用于已通过其他工具解码 QR 码的场景。
    Useful when the QR code has already been decoded by another tool.
    """
    if not request.qr_content.strip():
        raise HTTPException(status_code=400, detail="QR content cannot be empty")

    result = await process_qr_content(request.qr_content)
    return KeyResponse(**result.to_dict())


@app.post("/api/key/offline", response_model=KeyResponse)
async def generate_offline_key(request: KeyRequest):
    """
    使用离线算法 v1 生成重置安全码（仅适用于旧设备，固件 < 5.3.0）。
    Generate a reset security code using the offline algorithm (serial number + date).

    使用海康威视专有离线算法（序列号+日期）生成重置安全码。
    ⚠️ 此算法仅适用于固件版本 < 5.3.0 的设备。新固件设备需通过海康威视官方渠道重置。
    ⚠️ This algorithm ONLY works for firmware < 5.3.0. Newer firmware requires Hikvision support.
    """
    if not request.serial.strip():
        raise HTTPException(status_code=400, detail="Serial number cannot be empty")
    if not request.date.strip():
        raise HTTPException(status_code=400, detail="Date cannot be empty")

    result = await generate_key_offline(request.serial.strip(), request.date.strip())
    return KeyResponse(**result.to_dict())


@app.post("/api/sadp/upload", response_model=SADPFileResponse)
async def upload_sadp_file(file: UploadFile = File(...)):
    """
    上传 SADP 导出的设备特征文件，解析设备序列号并尝试生成重置安全码。
    Upload a SADP-exported device characteristic file, extract serial numbers, attempt key generation.

    SADP 导出的设备特征文件为二进制格式（扩展名通常为 .xml），包含设备序列号等信息。
    上传后，系统将提取文件中的序列号并使用离线算法尝试生成安全码。
    ⚠️ 离线算法仅适用于固件 < 5.3.0。新固件设备需将此文件发送给海康威视官方获取重置文件。
    ⚠️ The offline algorithm ONLY works for firmware < 5.3.0. For newer firmware, send the file
    to Hikvision support to get the unlock file.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # 验证文件类型 / Validate file type
    content_type = file.content_type or ""
    is_valid_content_type = "xml" in content_type or "text" in content_type or "octet" in content_type
    is_valid_extension = (file.filename or "").lower().endswith((".xml", ".dat", ".txt"))
    if not (is_valid_content_type or is_valid_extension):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {content_type}. "
                "Please upload a SADP device characteristic file (.xml / .dat)."
            ),
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # 尝试多种编码解码文件内容（latin-1 在最后，因为它从不失败但可能误读中文）
    # Try multiple encodings; latin-1 last since it never fails but may misread Chinese
    file_content: str
    for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            file_content = file_bytes.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        raise HTTPException(status_code=400, detail="Cannot decode file — unsupported encoding")

    results = await process_sadp_device_file(file_content)

    if len(results) == 1 and results[0].key is None and results[0].error:
        # 文件级解析错误 / File-level parse error
        return SADPFileResponse(error=results[0].error, count=0)

    return SADPFileResponse(
        devices=[KeyResponse(**r.to_dict()) for r in results],
        count=len(results),
    )


@app.post("/api/sadp/discover", response_model=SADPDiscoveryResponse)
async def discover_sadp_devices(timeout: float = 5):
    """
    通过 SADP 协议在局域网中发现海康威视设备。
    Discover Hikvision devices on the local network via SADP protocol.

    自动获取设备的序列号、固件版本和启动时间（设备内部时钟）。
    Automatically retrieves device serial number, firmware version, and boot time (internal clock).

    这解决了以下问题 / This solves:
      - 用户无法获取设备时间 / Users unable to get device time
      - 需要手动查找序列号 / Need to manually look up serial numbers
      - 需要判断固件版本是否支持离线重置 / Need to determine if firmware supports offline reset

    ⚠️ 需要与设备在同一局域网内，且 UDP 端口 37020 未被防火墙阻止。
    ⚠️ Requires being on the same LAN as the device, and UDP port 37020 not blocked by firewall.
    """
    # 限制超时范围 / Limit timeout range
    timeout = max(1.0, min(timeout, 30.0))

    try:
        devices = await discover_devices(timeout=timeout)
        return SADPDiscoveryResponse(
            devices=[DiscoveredDeviceResponse(**d.to_dict()) for d in devices],
            count=len(devices),
        )
    except Exception as exc:
        logger.warning("SADP discovery failed: %s", exc)
        return SADPDiscoveryResponse(
            error=(
                f"设备发现失败: {exc}. "
                "请确保与设备在同一局域网内，且 UDP 端口 37020 未被防火墙阻止。"
                f" / Discovery failed: {exc}. "
                "Ensure you are on the same LAN and UDP port 37020 is not blocked."
            ),
        )


# ---------------------------------------------------------------------------
# 生产模式：托管前端静态文件（单端口部署）
# Production mode: serve frontend static files (single-port deployment)
#
# 当 frontend/dist/ 目录存在时，自动挂载静态资源并将非 API 路径回退到 index.html，
# 实现 SPA 路由。开发模式下 dist/ 不存在，不影响开发体验。
# When frontend/dist/ exists, mount static assets and fall back non-API paths
# to index.html for SPA routing. In dev mode dist/ doesn't exist, so this is a no-op.
# ---------------------------------------------------------------------------

if _FRONTEND_DIST.is_dir():
    # 挂载 Vite 构建产物中的 assets 目录（JS/CSS/图片等）
    # Mount the Vite build assets directory (JS/CSS/images etc.)
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def _serve_frontend(full_path: str):
        """
        SPA 回退路由：尝试提供静态文件，否则返回 index.html。
        SPA fallback: serve the static file if it exists, otherwise return index.html.
        """
        # 尝试精确匹配文件（如 favicon.ico, robots.txt 等）
        # Try exact file match (e.g. favicon.ico, robots.txt)
        file_path = (_FRONTEND_DIST / full_path).resolve()
        # 防止路径遍历攻击 / Prevent path traversal attacks
        if full_path and file_path.is_file() and file_path.is_relative_to(_FRONTEND_DIST):
            return FileResponse(str(file_path))
        # 所有其他路径返回 index.html（Vue Router 处理客户端路由）
        # All other paths return index.html (Vue Router handles client-side routing)
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

    logger.info("Serving frontend from %s", _FRONTEND_DIST)


# ---------------------------------------------------------------------------
# 程序入口（通过 __main__ 直接运行）
# Entry point (when run directly via __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "hikresetpasswd.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
